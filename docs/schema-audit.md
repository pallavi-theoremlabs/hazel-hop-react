# Schema Audit — Hazel HOP

Read-only audit of what this application actually stores and how, derived from source at
commit `f290a8d`. Every claim below is anchored to a `file:line`.

**Summary of the storage layer.** One SQLite database, defined entirely in
`backend/app/db.py`. No `.sql` files, no migration directory, no ORM — `backend/requirements.txt`
lists only `fastapi`, `uvicorn`, `httpx`, `python-dotenv`, `python-multipart`. No client-side
persistence: the frontend has no `localStorage`, `sessionStorage`, `IndexedDB`, or service
worker. Seven tables, one index, 83 statement-executing call sites.

---

## 1. Schema

All DDL is a single `conn.executescript()` call at `backend/app/db.py:48-135`, run from
`init_db()` (`db.py:46`), which is invoked from the FastAPI lifespan handler at
`backend/app/main.py:17` — i.e. **on every process start**.

Three conventions apply across every table and are the root of most of the porting work:

- **All timestamps are `TEXT`**, holding Python-generated ISO-8601 strings from `utc_now()`
  (`db.py:25-26`). There is no `CURRENT_TIMESTAMP`, `julianday`, `strftime`, or `date()`
  anywhere in the codebase — 100% of time values originate in Python.
- **All booleans are `INTEGER`** 0/1.
- **All structured data is JSON hand-serialized into `TEXT`** columns with
  `json.dumps`/`json.loads`, defaulting to the string `'{}'`.

### 1.1 `onboarding_cases` — db.py:50-67

The hub table. One row per onboarding case; `id` is a human-readable string generated in
Python, not a surrogate key.

| Column | Type | Null | Default | Key |
|---|---|---|---|---|
| `id` | TEXT | NO | — | **PK** |
| `institution_id` | TEXT | NO | — | |
| `current_stage` | TEXT | NO | — | drives the stage machine (§2) |
| `nda_accepted_at` | TEXT | YES | — | timestamp-as-text |
| `institution_profile_completed_at` | TEXT | YES | — | timestamp-as-text |
| `documents_completed_at` | TEXT | YES | — | timestamp-as-text |
| `due_diligence_completed_at` | TEXT | YES | — | timestamp-as-text |
| `risk_questions_submitted_at` | TEXT | YES | — | timestamp-as-text |
| `coverbase_session_id` | TEXT | YES | — | external ref |
| `coverbase_vendor_id` | TEXT | YES | — | external ref |
| `coverbase_status` | TEXT | YES | — | external status |
| `hazel_review_status` | TEXT | YES | — | added by runtime migration, db.py:147 |
| `review_status` | TEXT | NO | `'Not started'` | |
| `additional_information_required` | INTEGER | NO | `0` | boolean-as-integer |
| `created_at` | TEXT | NO | — | timestamp-as-text |
| `updated_at` | TEXT | NO | — | timestamp-as-text |

`current_stage` has **no CHECK constraint**. The enum is enforced only in Python
(`db.py:211-212`).

### 1.2 `institution_profiles` — db.py:68-78

| Column | Type | Null | Default | Key |
|---|---|---|---|---|
| `case_id` | TEXT | NO | — | **PK**, **FK** → `onboarding_cases(id)` ON DELETE CASCADE |
| `legal_name` | TEXT | YES | — | |
| `fdic_certificate_number` | TEXT | YES | — | |
| `rssd_id` | TEXT | YES | — | |
| `institution_type` | TEXT | YES | — | |
| `website` | TEXT | YES | — | |
| `headquarters` | TEXT | YES | — | |
| `admission_type` | TEXT | YES | — | |
| `international_correspondent_relationships` | TEXT | YES | — | |
| `has_dba` | TEXT | YES | — | tri-state stored as text, not boolean |
| `has_fintech_or_baas_programs` | TEXT | YES | — | tri-state stored as text |
| `primary_contact_name` | TEXT | YES | — | |
| `primary_contact_title` | TEXT | YES | — | |
| `primary_contact_email` | TEXT | YES | — | |
| `additional_responses_json` | TEXT | NO | `'{}'` | JSON-in-text; added by migration db.py:140 |
| `updated_at` | TEXT | NO | — | timestamp-as-text |

### 1.3 `express_interest_submissions` — db.py:79-85

The pre-case inquiry snapshot. Deliberately duplicates profile fields so the original
submission is preserved even as the profile is edited.

| Column | Type | Null | Default | Key |
|---|---|---|---|---|
| `case_id` | TEXT | NO | — | **PK**, **FK** → `onboarding_cases(id)` ON DELETE CASCADE |
| `legal_name` | TEXT | YES | — | |
| `fdic_certificate_number` | TEXT | YES | — | |
| `rssd_id` | TEXT | YES | — | |
| `institution_type` | TEXT | YES | — | |
| `website` | TEXT | YES | — | |
| `headquarters` | TEXT | YES | — | |
| `contact_name` | TEXT | YES | — | |
| `contact_title` | TEXT | YES | — | |
| `contact_email` | TEXT | YES | — | |
| `data_json` | TEXT | NO | `'{}'` | JSON-in-text |
| `updated_at` | TEXT | NO | — | timestamp-as-text |

### 1.4 `documents` — db.py:86-98

The only table with a surrogate integer key.

| Column | Type | Null | Default | Key |
|---|---|---|---|---|
| `id` | INTEGER | NO | — | **PK AUTOINCREMENT** (db.py:87) |
| `case_id` | TEXT | NO | — | **FK** → `onboarding_cases(id)` ON DELETE CASCADE |
| `document_type` | TEXT | NO | — | |
| `original_name` | TEXT | NO | — | as uploaded |
| `stored_name` | TEXT | NO | — | on-disk filename (§4) |
| `size_bytes` | INTEGER | NO | — | |
| `created_at` | TEXT | NO | — | timestamp-as-text |
| `coverbase_document_id` | TEXT | YES | — | migration db.py:155-165 |
| `coverbase_sync_status` | TEXT | NO | `'not_started'` | migration |
| `coverbase_synced_at` | TEXT | YES | — | migration |
| `coverbase_sync_error` | TEXT | YES | — | migration |
| `coverbase_sync_details_json` | TEXT | NO | `'{}'` | migration; JSON-in-text |
| `file_sha256` | TEXT | YES | — | migration; drives content dedupe at cases.py:241-248 |

**No index on `case_id`**, despite it being the filter on every document query
(`cases.py:674`, `747`, `779`, `168`, `112`).

### 1.5 `due_diligence` — db.py:99-102

| Column | Type | Null | Default | Key |
|---|---|---|---|---|
| `case_id` | TEXT | NO | — | **PK**, **FK** → `onboarding_cases(id)` ON DELETE CASCADE |
| `data_json` | TEXT | NO | `'{}'` | the entire questionnaire, unmodelled |
| `updated_at` | TEXT | NO | — | timestamp-as-text |

### 1.6 `risk_answers` — db.py:103-108

| Column | Type | Null | Default | Key |
|---|---|---|---|---|
| `case_id` | TEXT | NO | — | **PK** (composite), **FK** → `onboarding_cases(id)` ON DELETE CASCADE |
| `question_id` | TEXT | NO | — | **PK** (composite) |
| `answer` | TEXT | NO | — | |
| `confirmed` | INTEGER | NO | `0` | boolean-as-integer |
| `updated_at` | TEXT | NO | — | timestamp-as-text |

**This table is dead.** It is created here and deleted from at `dev.py:124`, but there is no
`INSERT` and no `SELECT` against it anywhere in the codebase. Risk answers actually live in
Coverbase, reached through `coverbase_session_id`.

### 1.7 `review_clarifications` — db.py:109-131

The only table with a DB-enforced enum.

| Column | Type | Null | Default | Key |
|---|---|---|---|---|
| `id` | TEXT | NO | — | **PK** |
| `case_id` | TEXT | NO | — | **FK** → `onboarding_cases(id)` ON DELETE CASCADE |
| `source` | TEXT | NO | — | |
| `source_reference_id` | TEXT | YES | — | |
| `requested_by` | TEXT | NO | — | free text, not a user FK |
| `request_text` | TEXT | NO | — | |
| `request_type` | TEXT | NO | `'additional_information'` | |
| `question_id` | TEXT | YES | — | |
| `requested_at` | TEXT | NO | — | timestamp-as-text |
| `due_at` | TEXT | YES | — | timestamp-as-text |
| `status` | TEXT | NO | — | **CHECK** `IN ('open','draft','submitted','resolved')` (db.py:130) |
| `member_response` | TEXT | NO | `''` | |
| `submitted_at` | TEXT | YES | — | timestamp-as-text |
| `document_required` | INTEGER | NO | `0` | boolean-as-integer |
| `document_label` | TEXT | YES | — | |
| `replacement_of_hazel_document_id` | INTEGER | YES | — | **FK** → `documents(id)` ON DELETE SET NULL |
| `uploaded_hazel_document_id` | INTEGER | YES | — | **FK** → `documents(id)` ON DELETE SET NULL |
| `coverbase_sync_status` | TEXT | NO | `'not_started'` | always `'pending_integration'` in practice |
| `created_at` | TEXT | NO | — | timestamp-as-text |
| `updated_at` | TEXT | NO | — | timestamp-as-text |

### 1.8 Indexes

Exactly one explicit index in the entire schema, at **db.py:132-133**:

```sql
CREATE INDEX IF NOT EXISTS idx_review_clarifications_case
ON review_clarifications(case_id, requested_at DESC);
```

Everything else relies on implicit primary-key indexes. Note the index sorts `requested_at`
descending — a **TEXT** column — so it is a lexicographic ordering that happens to coincide
with chronological order only because every value is a zero-padded ISO-8601 string from the
same generator.

### 1.9 Runtime migrations

There is no migration table and no schema version. `init_db()` performs idempotent additive
migrations by probing `PRAGMA table_info` and issuing `ALTER TABLE ... ADD COLUMN`:

| Probe | Adds | Lines |
|---|---|---|
| `PRAGMA table_info(institution_profiles)` | `additional_responses_json` | db.py:136-142 |
| `PRAGMA table_info(onboarding_cases)` | `hazel_review_status` + a backfill UPDATE | db.py:143-151 |
| `PRAGMA table_info(documents)` | six columns via an f-string loop | db.py:152-165 |

**Gap:** `review_clarifications` has no corresponding migration block. A database created
before that table gained its current columns — or its `CHECK` constraint — would not be
upgraded, because `CREATE TABLE IF NOT EXISTS` silently no-ops on an existing table.

### 1.10 Seed data

`init_db()` also seeds the fixture case `HAZEL-TEST-001` (Northstar Community Bank, N.A.)
via four `INSERT OR IGNORE` statements at db.py:167-200, the last of which is an
`INSERT ... SELECT` that derives the express-interest row from the profile row.

---

## 2. Relationships and the case lifecycle

### 2.1 Relationships

A pure star. `onboarding_cases.id` is the hub; all six other tables reference it and cascade
on delete. `review_clarifications` is the only table with a second relationship, referencing
`documents` twice with `ON DELETE SET NULL`.

```
                        onboarding_cases (id)
                                 |
    +--------------+-------------+-------------+---------------+
    |              |             |             |               |
institution_   express_      documents    due_diligence   risk_answers
 profiles      interest_     (id serial)   (case_id PK)   (case_id,
(case_id PK)   submissions        ^                        question_id PK)
               (case_id PK)       |                         [DEAD - never
                                  |                          read or written]
                        review_clarifications
                        - replacement_of_hazel_document_id -> documents(id) SET NULL
                        - uploaded_hazel_document_id       -> documents(id) SET NULL
```

Cascades are only enforced because `PRAGMA foreign_keys = ON` is issued on **every**
connection at `db.py:34` — SQLite defaults foreign keys off, per-connection.

### 2.2 The stage machine

**Where stage lives:** `onboarding_cases.current_stage TEXT NOT NULL` (`db.py:53`).

**The stage values** — Python-side only, `db.py:14-22`:

```python
STAGES = [
    "NDA_PENDING",
    "NDA_ACCEPTED",
    "INSTITUTION_PROFILE",
    "DOCUMENTS",
    "DUE_DILIGENCE",
    "RISK_QUESTIONS",
    "HAZEL_REVIEW",
]
```

The list is ordinal: order in the list *is* the progression order, and `.index()` is used for
comparison at `db.py:215` and `cases.py:327`.

**The single writer** is `update_stage()` at `db.py:210-223`. It validates membership
(raises `ValueError` on an unknown stage) and is **monotonic** — db.py:215-216 refuses to
move a case backwards:

```python
if current and STAGES.index(current["current_stage"]) > STAGES.index(stage):
    effective_stage = current["current_stage"]
```

**Every stage write:**

| file:line | Writes | Trigger |
|---|---|---|
| `db.py:167-172` | `'NDA_PENDING'` | `init_db()` seeds `HAZEL-TEST-001` |
| `public.py:32-38` | `'NDA_PENDING'` | `POST /api/public/submit-interest` |
| `dev.py:52-58` | `'NDA_PENDING'` | `POST /api/dev/create-case` |
| `dev.py:103-114` | `'NDA_PENDING'` — **bypasses `update_stage()`** with a raw UPDATE, also nulling all `*_at`, `hazel_review_status`, and the Coverbase columns | `POST /api/dev/reset-case/{case_id}` |
| `cases.py:426` | → `'INSTITUTION_PROFILE'`, sets `nda_accepted_at` | `POST .../nda/accept` |
| `cases.py:666` | → `'DOCUMENTS'`, sets `institution_profile_completed_at` | `POST .../institution-profile/complete` |
| `cases.py:793` | → `'DUE_DILIGENCE'`, sets `documents_completed_at` | `POST .../documents/complete` |
| `cases.py:821` | → `'RISK_QUESTIONS'`, sets `due_diligence_completed_at` | `POST .../due-diligence/complete` |
| `cases.py:904-915` | → `'HAZEL_REVIEW'`, sets `risk_questions_submitted_at`, `coverbase_status`, `hazel_review_status`, `review_status` | `POST .../risk-questions/submit` |

`dev.py:103-114` is the only write that moves a case backwards, and it does so precisely by
avoiding the monotonic guard.

**Gates.** `require_at_least()` (`cases.py:330-332`) raises 409 for profile, documents,
diligence and review endpoints. Risk-question writes instead use exact equality
(`cases.py:869`, `cases.py:1195`: `if case["current_stage"] != "RISK_QUESTIONS"`) so that
answers are frozen after final submission.

**Two divergences worth recording:**

1. `NDA_ACCEPTED` is in the enum but **never written by any code path** — `accept_nda`
   (`cases.py:426`) jumps straight from `NDA_PENDING` to `INSTITUTION_PROFILE`. It exists
   only to occupy an ordinal slot.
2. The frontend maintains three near-duplicate stage lists that do not match the backend:
   `ProgressTracker.jsx:3-21` omits `NDA_ACCEPTED` entirely and special-cases it to index 0,
   so backend ordinal N ≠ frontend ordinal N; `PROGRESS_STAGES` (`ProgressTracker.jsx:12-16`)
   appends two display-only stages, `'ESIGN'` and `'ACCOUNT_OPENING'`, that exist nowhere in
   the backend; and `AppShell.jsx:9-14` holds a third copy.

### 2.3 The second, orthogonal status machine

Separate from `current_stage`, the columns `hazel_review_status` and `review_status` track
review outcome: `under_review`, `approved`, `rejected`, `partial`, `action_required`,
`response_submitted`. Computed by `review_state_for()` (`models/clarifications.py:29-44`)
and mapped from Coverbase's vocabulary by `REVIEW_STATUS_MAP` (`cases.py:46-52`). Written at
`cases.py:984` (on every review poll — see §3), `cases.py:1063`, `cases.py:1112`,
`cases.py:1157`, and `dev.py:197`.

---

## 3. Persistence call-site inventory

83 statement-executing call sites, all funnelled through one helper — `connection()` at
`db.py:29-39`:

```python
@contextmanager
def connection():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)   # filesystem write per open
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
```

A new connection per `with` block; no pooling, no `check_same_thread`, no WAL, no
`busy_timeout`, and **no `rollback()`** — on an exception the commit is skipped and `close()`
discards the implicit transaction.

### 3.1 `backend/app/db.py` — 15 sites

| Line | Function | Operation |
|---|---|---|
| 34 | `connection` | PRAGMA foreign_keys |
| 48 | `init_db` | `executescript` — full DDL |
| 137, 144, 153 | `init_db` | `PRAGMA table_info` migration probes |
| 140, 147, 165 | `init_db` | `ALTER TABLE ... ADD COLUMN` (165 is an f-string loop) |
| 148 | `init_db` | UPDATE — `hazel_review_status` backfill |
| 167, 173, 186, 190 | `init_db` | `INSERT OR IGNORE` seed (190 is INSERT…SELECT) |
| 204 | `require_case` | SELECT `onboarding_cases` — reached ~25× indirectly via `get_or_404` |
| 223 | `update_stage` | UPDATE — **f-string column interpolation from `**fields`** |

### 3.2 `backend/app/routers/cases.py` — 48 sites

| Line | Function | Operation / note |
|---|---|---|
| 103 | `load_review_clarifications` | SELECT, `ORDER BY requested_at DESC, created_at DESC` — lexical sort on TEXT dates |
| 112 | `load_review_clarifications` | SELECT `documents` — **N+1 inside a Python loop** |
| 168, 181 | `backfill_case_document_hashes` | SELECT then UPDATE **inside a loop** |
| 194, 199 | `sync_hazel_document` | UPDATE + read-back (transaction 1 of 4) |
| 235, 241 | `sync_hazel_document` | UPDATE `file_sha256`; SELECT dedupe `ORDER BY created_at, id LIMIT 1` (txns 2–3) |
| 289, 303 | `sync_hazel_document` | UPDATE 6 columns + read-back (txn 4) |
| 339 | `get_case` | SELECT `express_interest_submissions` |
| 364, 375, 385 | `ensure_coverbase_session` | SELECT; error-path UPDATE; **conditional UPDATE guarded by `WHERE ... AND coverbase_session_id IS NULL`** with no rowcount check |
| 449, 456, 518, 535 | profile reads | SELECT `institution_profiles` |
| **561** | `save_institution_profile_responses` | **`INSERT ... ON CONFLICT(case_id) DO UPDATE`** — column list *and* assignment list f-string-interpolated; placeholder count is dynamic |
| **628** | `save_institution_profile` | **dynamic f-string UPDATE**, columns from Pydantic model keys |
| 632, 641, 644 | profile complete | SELECT |
| 674 | `get_documents` | SELECT `ORDER BY created_at DESC` — unbounded, no pagination |
| **704** | `upload_document` | **INSERT `documents`** |
| **711** | `upload_document` | **SELECT by `cursor.lastrowid`** — the only `lastrowid` in the repo |
| 727 | `retry_document_coverbase_sync` | SELECT |
| 741, **744**, 747 | `delete_document` | SELECT; **DELETE**; SELECT `LIMIT 1` **with no ORDER BY** |
| 779 | `complete_documents` | SELECT `ORDER BY created_at DESC, id DESC LIMIT 1` |
| 801, **811** | due diligence | SELECT; **UPDATE with no upsert** — silently no-ops with HTTP 200 if the row was never seeded |
| **984** | `build_hazel_review_payload` | **UPDATE `onboarding_cases`, executed on every `GET /hazel-review` and every poll of `/hazel-review/status`** — the frontend polls this on a 10 s/30 s timer (`useCoverbaseReviewStatus.js:5`), so a read endpoint generates continuous writes |
| 1050, 1058, 1063, 1070, 1074 | `save_clarification_draft` | SELECT, UPDATE ×2, SELECT ×2 |
| 1091, 1107, 1112, 1119 | `upload_clarification_document` | SELECT, UPDATE ×2, SELECT — spans 3 transactions |
| 1136, 1151, 1157, 1164, 1168 | `submit_clarification_response` | SELECT, UPDATE ×2, SELECT ×2 |

### 3.3 `backend/app/routers/dev.py` — 16 sites

| Line | Function | Operation |
|---|---|---|
| 34 | `case_payload` | SELECT |
| 52, 59, 75, 79 | `create_case` | INSERT ×4 (cases, express interest, profile, diligence) |
| 97 | `reset_case` | SELECT `stored_name` — drives the file-deletion loop at dev.py:134-139 |
| 103, 115 | `reset_case` | UPDATE ×2 (103 nulls 11 columns, bypassing `update_stage`) |
| 122, 123, 124 | `reset_case` | DELETE `documents`, `review_clarifications`, `risk_answers` |
| **125** | `reset_case` | **`INSERT ... ON CONFLICT(case_id) DO UPDATE ... excluded.updated_at`** |
| 168, 174, 197, 204 | `create_review_clarification` | SELECT FK validation; INSERT (20 columns); UPDATE; SELECT |

### 3.4 `backend/app/routers/public.py` — 4 sites

`submit_interest` (public.py:32, 39, 57, 61) inserts into all four base tables inside one
`connection()` block — the only place in the codebase where a multi-table logical operation
is correctly atomic.

### 3.5 The SQLite-ism table — **this is the porting checklist**

| # | SQLite-ism | file:line | Postgres equivalent |
|---|---|---|---|
| 1 | `?` positional placeholders — **every** parameterized statement; zero named params, zero `%s` | all 83 sites across `db.py`, `cases.py`, `dev.py`, `public.py` | `%s` (psycopg) |
| 2 | `sqlite3.connect(path)` | `db.py:32` | pooled `psycopg.connect(conninfo)` |
| 3 | `conn.row_factory = sqlite3.Row` | `db.py:33` | `psycopg.rows.dict_row` — consumers use both `dict(row)` and `row["col"]`, which dicts satisfy |
| 4 | `PRAGMA foreign_keys = ON` (per connection) | `db.py:34` | delete — always enforced |
| 5 | `executescript()` | `db.py:48` | numbered migration files |
| 6 | `INTEGER PRIMARY KEY AUTOINCREMENT` | `db.py:87` | `bigint GENERATED BY DEFAULT AS IDENTITY` |
| 7 | `PRAGMA table_info(...)` as a migration probe | `db.py:137`, `db.py:144`, `db.py:153` | delete — replaced by migrations |
| 8 | runtime `ALTER TABLE ... ADD COLUMN` | `db.py:140`, `db.py:147`, `db.py:165` (f-string loop) | delete |
| 9 | `INSERT OR IGNORE` | `db.py:168`, `db.py:174`, `db.py:187`, `db.py:191` | `ON CONFLICT DO NOTHING` |
| 10 | `ON CONFLICT ... DO UPDATE` / `excluded.` | `cases.py:564`, `dev.py:127` | **unchanged** — PG-native syntax that SQLite borrowed |
| 11 | `cursor.lastrowid` | `cases.py:712` | `INSERT ... RETURNING *` |
| 12 | f-string interpolation of **column names** | `db.py:220-223`, `cases.py:557-565`, `cases.py:627-629` | whitelist column names against a fixed set |
| 13 | ISO-8601 dates in `TEXT`; lexical ordering | generated `db.py:25-26`; sorted at `db.py:133`, `cases.py:105`, `cases.py:246`, `cases.py:675`, `cases.py:782` | `timestamptz` + real temporal ordering |
| 14 | booleans as `INTEGER` 0/1 | written `cases.py:996`, `cases.py:1064`, `cases.py:1113`, `cases.py:1158`, `dev.py:190`, `dev.py:198`; read `cases.py:345`, `models/clarifications.py:24` | `boolean` |
| 15 | JSON hand-serialized into `TEXT` | `cases.py:68, 79, 90, 214, 299, 555, 560, 630, 802, 811`, `dev.py:71`, `public.py:53` | `jsonb` |
| 16 | commit-on-success with **no rollback** | `db.py:35-39` | psycopg context manager rolls back on exception |
| 17 | one logical operation across 4 connections | `cases.py:194, 235, 241, 289` (`sync_hazel_document`); 3 at `cases.py:1091-1119` | single transaction |
| 18 | `LIMIT 1` with **no `ORDER BY`** | `cases.py:749` | add a deterministic order |
| 19 | no pagination on unbounded reads | `cases.py:674`, `cases.py:779`, `cases.py:103` | note only |
| 20 | UPDATE with no upsert against a possibly-absent row | `cases.py:811` | `ON CONFLICT` or an existence check |
| 21 | conditional UPDATE used as a lock, no rowcount check | `cases.py:385-396` | `RETURNING` + rowcount, or a real lock |

---

## 4. Files on disk, path construction, and controlling env vars

### 4.1 Write sites

| # | file:line | What |
|---|---|---|
| 1 | `db.py:31` | `DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)` — runs on **every** connection open |
| 2 | `db.py:32` | the SQLite database file itself (plus `-wal`/`-shm`) |
| 3 | `cases.py:699` | `UPLOAD_DIR.mkdir(parents=True, exist_ok=True)` — runs on every upload |
| 4 | `cases.py:700` | `(UPLOAD_DIR / stored_name).write_bytes(contents)` — the uploaded document |
| 5 | `cases.py:716` | `unlink(missing_ok=True)` — compensating delete when the INSERT fails |
| 6 | `cases.py:752` | `(UPLOAD_DIR / row["stored_name"]).unlink(missing_ok=True)` |
| 7 | `dev.py:137` | `(UPLOAD_DIR / safe_name).unlink(missing_ok=True)` in a loop over `reset_case` documents |

Read sites: `cases.py:175` (SHA-256 backfill) and `cases.py:231` (re-read for Coverbase sync).

Only three operations are ever performed on the uploads directory — `write_bytes`,
`read_bytes`, `unlink` — plus `mkdir`. No random access, no rename, no append, no `tempfile`,
no `shutil`. That narrow surface is what makes an object-store or Volume backing viable.

### 4.2 Path construction

Stored filenames are built at `cases.py:697-698`:

```python
safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(original_name).stem).strip("-") or "document"
stored_name = f"{case_id}-{uuid4().hex}-{safe_stem}{suffix}"
```

The extension is whitelisted at `cases.py:42` (`.pdf .doc .docx .xls .xlsx`) and size capped
at 25 MB (`cases.py:43`). Names are collision-free by construction and contain no path
separators.

**Inconsistency:** `cases.py:752` joins the raw database value, whereas every other site
defensively re-basenames it with `Path(...).name` (`cases.py:173`, `cases.py:228`,
`dev.py:135`). Harmless today because `stored_name` is always generated, not user-supplied,
but it is the odd one out.

### 4.3 Env vars

Both path variables re-anchor relative values to `BACKEND_DIR`, so the current working
directory never affects them — and both already accept an absolute path, which is what makes
relocating storage a configuration change rather than a rewrite.

| Var | file:line | Default | Controls |
|---|---|---|---|
| `DATABASE_PATH` | `db.py:10-12` | `backend/hazel_hop.db` | SQLite file location |
| `UPLOAD_DIR` | `cases.py:39-41` | `backend/uploads` | document storage directory |
| `COVERBASE_MODE` | `config.py:32` | `mock` | mock vs live adapter; validated to `{mock,live}` |
| `COVERBASE_BASE_URL` | `config.py:33` | `""` → **fatal** | required even in mock mode |
| `COVERBASE_API_KEY` | `config.py:34` | `""` | required iff live |
| `COVERBASE_QUESTIONNAIRE_ID` | `config.py:35` | `""` | required at session create |
| `FRONTEND_ORIGIN` | `main.py:24` | `http://localhost:5173` | the single allowed CORS origin |
| `HAZEL_DEV_MODE` | `dev.py:17` | `false` | gates **only** the synthetic-clarification endpoint |
| `VITE_API_BASE_URL` | `frontend/src/services/api.js:1` | `http://localhost:8000` | API origin, baked in at build time |
| `VITE_DEV_MODE` | `AppShell.jsx:6` + 5 others | unset | dev panels; review poll interval 10 s vs 30 s |

---

## 5. Assumptions that break on a restart, a second worker, or a non-local filesystem

### 5.1 Local writable filesystem

- **The SQLite database** (`db.py:10-12`, `db.py:32`). A single file with no network
  protocol. On ephemeral container storage the entire dataset is lost on redeploy; on shared
  storage it corrupts under concurrent writers. `.gitignore:7` (`*.db`) confirms it is
  treated as disposable.
- **The uploads directory** (`cases.py:39-41`). Same lifetime problem, and with two
  processes on separate volumes an upload written by one is invisible to the other.
- **`mkdir` on every operation** (`db.py:31`, `cases.py:699`). Assumes the parent is
  creatable, which is not true of every mounted-volume root.

### 5.2 Local process — in-memory state

All of it lives on one module-level singleton, `coverbase_service = CoverbaseService()` at
`coverbase.py:1696`, instantiated at import. Fields declared at `coverbase.py:116-123`:

| Field | coverbase.py | Consequence |
|---|---|---|
| **`_pending_questionnaire_saves`** | declared 123, checked **1171**, mutated **1300-1312** | **A correctness break, not merely a durability one.** It is a cross-request mutex preventing a final submission while a Risk-Question save is in flight. The check at line 1171 is **unconditional — it guards live mode as well as mock.** With two workers, a save handled by worker A and a submit handled by worker B never see each other's counter, the guard silently passes, and the submission is sent mid-write. It also leaks a permanent "pending" state if the process dies between increment and decrement. |
| `_mock_questionnaire_response_overrides` | 120-122; written 1451, read 269-271 | Every risk-question answer entered in mock mode exists **only here**. Lost on restart, invisible to a second worker. |
| `_mock_session_statuses` | 119; written 189, 1239, read 250 | A restart reverts a submitted mock session to `open`. |
| `_mock_selected_use_cases` | 116; written 758, read 260, 583 | If empty, `_mock_ai_generated_followups` returns `[]` (583-584), which sends the caller into the 20 × 2 s poll loop at 698-713 — a **40-second stall** on every pre-existing session after a restart. |
| `_mock_document_ids` | 117; written 472, 531, read 266 | Mock document attachments vanish on restart. |
| `_mock_documents` | 118; written 314, read 556 | A missing entry raises `RuntimeError` at coverbase.py:558. |

These six diverge from SQLite, which *does* persist `coverbase_session_id` across restarts —
so after a restart the database points at a session the service no longer knows anything
about.

**Nothing else in the codebase holds mutable process state.** There are no threads, no
`asyncio.create_task`, no `BackgroundTasks`, no job queue, no cache, no rate limiter, no
WebSocket or SSE registry, and no session store. The remaining module-level values
(`STAGES`, `REVIEW_STATUS_MAP`, `ALLOWED_EXTENSIONS`, `HAZEL_INSTITUTION_PROFILE_SCHEMA`, …)
are read-only constants.

### 5.3 Configuration frozen at import

`config.py:14-15` raises `RuntimeError` at **import time** if `backend/.env` does not exist.
This fires before the lifespan handler, so the process cannot start at all. `settings`
(`config.py:31-36`), `DATABASE_PATH`, `UPLOAD_DIR`, `DEV_MODE_ENABLED` (`dev.py:17`) and the
CORS origin (`main.py:24`) are all evaluated once at import, so every configuration change
requires a restart. `load_dotenv(override=False)` means real process environment variables
correctly win over the file.

### 5.4 Other restart/concurrency hazards

- **`init_db()` runs on every process start** (`main.py:17`), executing DDL. Two workers
  starting simultaneously race on `CREATE TABLE IF NOT EXISTS` and the `ALTER TABLE`
  migrations.
- **Read-modify-write on stage** (`db.py:213-223`): `update_stage` reads `current_stage`,
  compares ordinals in Python, then writes — with no locking. Two concurrent transitions can
  lose an update.
- **A read endpoint that writes** (`cases.py:984`), driven by a client-side polling timer.
- **File-before-database ordering** (`cases.py:699-700` writes the file before the INSERT at
  704, compensating at 716). And in `delete_document` the transaction commits at
  `cases.py:751` *before* the file is unlinked at 752 and before the Coverbase call that can
  raise 502 at `cases.py:768` — so the row and the file are already gone when the client sees
  the error.
- **Synchronous `sqlite3` inside `async def` handlers** throughout `cases.py`
  (`upload_document`, `sync_hazel_document`, `build_hazel_review_payload`, …), blocking the
  event loop for the duration of every query.
- **No HTTP connection reuse**: a fresh `httpx.AsyncClient` is constructed and torn down per
  call at 17 sites in `coverbase.py`.

---

## 6. What is *not* in the schema

Recorded because the production target assumes them:

- **No tenancy.** No `org_id`, `tenant_id`, or any equivalent on any table. Every query is
  scoped by `case_id` alone.
- **No users.** `requested_by` (`db.py:114`) is free text. There is no user table, no auth,
  no session, and no authorization check anywhere in the backend.
- **No audit or decision history.** Status changes overwrite in place; `review_clarifications`
  is the closest thing to an event log, and it too is mutated in place
  (`cases.py:1058`, `1107`, `1151`).
- **No soft delete.** `DELETE` is physical (`cases.py:744`, `dev.py:122-124`).
- **No row-level security**, and no column on which it could currently be predicated.
