# Databricks Deployment Plan — Hazel HOP

Target: **one Databricks App**. FastAPI serves `/api/*` and the built React bundle from the
same origin. **Lakebase Postgres** for data, a **Unity Catalog Volume** for uploads,
**Coverbase in mock mode**.

Companion document: [`schema-audit.md`](./schema-audit.md). Section 3.5 of that document is
the porting checklist this plan is keyed to; items below cite it as **[C-n]**.

### Decision on record

This deployment is the **seed of the production system**, not a throwaway. Consequently the
port absorbs three production requirements in the same pass that rewrites the call sites:
`org_id` on every table, `timestamptz` for every timestamp, and an append-only decision
record. Row-level security is in scope. The reasoning: the port touches all 83 call sites
exactly once, and re-touching them later costs a second full pass *plus* a data migration on
live rows. §10 lists what is still deliberately deferred and what undoing each will cost.

### Platform constraints this plan is built around

| Constraint | Consequence here |
|---|---|
| Apps set `DATABRICKS_APP_PORT`, and `UVICORN_PORT` to the same value. `app.yaml`'s `command` is a YAML array exec'd **without a shell**, so `$VAR` is not expanded. | Pass **no** `--port`. Let uvicorn read `UVICORN_PORT` itself. (§5) |
| Lakebase OAuth tokens expire after ~60 minutes. | The token is the Postgres password and must be minted **per connection**, never once at startup. (§4) |
| A role from `databricks_create_role(<client_id>, 'SERVICE_PRINCIPAL')` starts with PUBLIC only; `GRANT CONNECT` alone cannot create a table. | Full grant set including `ALTER DEFAULT PRIVILEGES`. (§1) |
| Apps does not run `npm run build`. | `frontend/dist/` must be committed. (§3.3) |
| Sizes are Medium (2 vCPU / 6 GB) and Large (4 vCPU / 12 GB). Horizontal scaling is Beta. | Medium, scaling off. (§6) |
| No anonymous access — every user has a Databricks identity. | Removes the need for app-level auth *to reach* the app, but does **not** give the app a user model. (§10.2) |

---

## 1. Tenant prerequisites and the exact SQL

### 1.1 Prerequisites

1. A Lakebase Postgres instance, with its instance name recorded.
2. A database (below: `hazel_hop`) and a dedicated schema (`hazel`) — do not use `public`.
3. A Unity Catalog Volume for uploads, e.g. `hazel.onboarding.uploads`, with the app's
   service principal granted `READ VOLUME` and `WRITE VOLUME`, plus `USE CATALOG` and
   `USE SCHEMA` on its parents.
4. The Databricks App created, and its **service principal client ID** recorded — this is
   the Postgres role name throughout.

### 1.2 Role creation and grants

Run as a Postgres superuser / instance owner. `<client_id>` is the app service principal's
client ID, and it must be double-quoted everywhere because it is a UUID.

```sql
-- 1. Create the role. It begins with PUBLIC privileges only.
SELECT databricks_create_role('<client_id>', 'SERVICE_PRINCIPAL');

-- 2. Reach the database and the schema.
GRANT CONNECT ON DATABASE hazel_hop TO "<client_id>";
GRANT USAGE  ON SCHEMA hazel        TO "<client_id>";

-- 3. Create objects in it. GRANT CONNECT alone does NOT permit CREATE TABLE;
--    without this the first migration fails with "permission denied for schema hazel".
GRANT CREATE ON SCHEMA hazel TO "<client_id>";

-- 4. Read and write existing objects.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA hazel TO "<client_id>";
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA hazel TO "<client_id>";

-- 5. And objects that do not exist yet. Steps 4 and 5 are NOT redundant:
--    step 4 covers today's tables, step 5 covers every table a future migration adds.
--    Without this, each new migration silently produces tables the app cannot read.
ALTER DEFAULT PRIVILEGES IN SCHEMA hazel
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "<client_id>";
ALTER DEFAULT PRIVILEGES IN SCHEMA hazel
  GRANT USAGE, SELECT ON SEQUENCES TO "<client_id>";

-- 6. Make the schema the app's default resolution path.
ALTER ROLE "<client_id>" SET search_path = hazel;
```

`ALTER DEFAULT PRIVILEGES` applies to objects created by *the role that runs it*. If the
migration role and the app role differ (§10.3), run step 5 as the migration role, or add
`FOR ROLE <migration_role>`.

### 1.3 Two ownership consequences that bite the RLS work

Both follow from the app role creating its own tables. Neither is obvious, and both silently
produce a system that *looks* secured and is not.

**A table owner bypasses RLS.** `ENABLE ROW LEVEL SECURITY` does not apply to the table's
owner. Since the app role runs the migrations and therefore owns every table, policies would
be inert against exactly the role they are meant to constrain. Every protected table needs
both:

```sql
ALTER TABLE hazel.onboarding_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel.onboarding_cases FORCE  ROW LEVEL SECURITY;   -- without this, RLS is a no-op for the owner
```

**An owner ignores its own revocations.** The append-only decision record cannot be enforced
with `REVOKE UPDATE, DELETE` while the app role owns the table — owners retain full rights
regardless. It must be enforced by a trigger (§2.4).

---

## 2. The SQLite → Postgres port

### 2.1 Mechanical conversions, keyed to the checklist

| Checklist | Change | Sites |
|---|---|---|
| **[C-1]** | `?` → `%s` | all 83 |
| **[C-2]** | `sqlite3.connect` → pooled `psycopg` (§4) | `db.py:32` |
| **[C-3]** | `sqlite3.Row` → `psycopg.rows.dict_row`. Low churn: consumers use both `dict(row)` and `row["col"]`, and a plain dict satisfies both, so `row_dict()` (`db.py:42-43`) becomes near-identity | `db.py:33` |
| **[C-4]** | delete `PRAGMA foreign_keys` — always enforced | `db.py:34` |
| **[C-5]**, **[C-7]**, **[C-8]** | delete `executescript`, the three `PRAGMA table_info` probes and the three `ALTER TABLE` blocks; replace with numbered migration files | `db.py:48`, `137`, `144`, `153`, `140`, `147`, `165` |
| **[C-6]** | `INTEGER PRIMARY KEY AUTOINCREMENT` → `bigint GENERATED BY DEFAULT AS IDENTITY` | `db.py:87` |
| **[C-9]** | `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING` | `db.py:168, 174, 187, 191` |
| **[C-10]** | **no change** — `ON CONFLICT ... DO UPDATE` and `excluded.` are PG-native | `cases.py:564`, `dev.py:127` |
| **[C-11]** | `cursor.lastrowid` → `INSERT ... RETURNING *`, which also collapses the INSERT and the read-back at `cases.py:711` into one statement | `cases.py:712` |
| **[C-13]** | TEXT dates → `timestamptz`; `utc_now()` returns a `datetime`, not a string. This *fixes* the lexical sorts at `cases.py:105, 246, 675, 782` rather than merely porting them | `db.py:25-26` + 5 sorts |
| **[C-14]** | INTEGER 0/1 → `boolean`. `bool(...)` reads at `cases.py:345` keep working | 6 write sites |
| **[C-15]** | TEXT JSON → `jsonb`. psycopg3 adapts `dict` via `Jsonb(...)`; the ~12 `json.dumps`/`loads` calls become pass-through | 12 sites |
| **[C-16]** | `connection()` becomes a pool checkout whose context manager rolls back on exception | `db.py:29-39` |
| **[C-18]** | add `ORDER BY created_at, id` to the bare `LIMIT 1` | `cases.py:749` |
| **[C-20]** | `cases.py:811` UPDATE → upsert, so saving due diligence cannot silently return 200 having written nothing | `cases.py:811` |
| **[C-21]** | `cases.py:385-396` conditional UPDATE → add `RETURNING` and check rowcount | `cases.py:385` |

**[C-12]** (f-string column interpolation at `db.py:220-223`, `cases.py:557-565`,
`cases.py:627-629`) is not injectable today — names come from a fixed schema constant and
Pydantic model keys — but for a production seed it should be hardened now, while the code is
already open: validate each name against an explicit allow-set derived from the same schema
constant and raise on a miss.

**[C-17]** (`sync_hazel_document` spanning four connections) and **[C-19]** (no pagination)
are left as-is; see §10.5.

### 2.2 The production shape

Applied in the same migration that creates the ported tables.

**Every table gains `org_id`:**

```sql
CREATE TABLE hazel.organizations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        text NOT NULL UNIQUE,
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
```

Representative ported table — the type mapping generalizes to the other six:

```sql
CREATE TABLE hazel.onboarding_cases (
    id                                text        PRIMARY KEY,
    org_id                            uuid        NOT NULL REFERENCES hazel.organizations(id),
    institution_id                    text        NOT NULL,
    current_stage                     text        NOT NULL,
    nda_accepted_at                   timestamptz,
    institution_profile_completed_at  timestamptz,
    documents_completed_at            timestamptz,
    due_diligence_completed_at        timestamptz,
    risk_questions_submitted_at       timestamptz,
    coverbase_session_id              text,
    coverbase_vendor_id               text,
    coverbase_status                  text,
    hazel_review_status               text,
    review_status                     text        NOT NULL DEFAULT 'Not started',
    additional_information_required   boolean     NOT NULL DEFAULT false,
    created_at                        timestamptz NOT NULL DEFAULT now(),
    updated_at                        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT onboarding_cases_stage_valid CHECK (current_stage IN (
        'NDA_PENDING','NDA_ACCEPTED','INSTITUTION_PROFILE','DOCUMENTS',
        'DUE_DILIGENCE','RISK_QUESTIONS','HAZEL_REVIEW'))
);
```

Note the `CHECK` on `current_stage`. The enum has lived only in Python (`db.py:14-22`) with
no database enforcement; a production seed should have both. Keep `STAGES` as the single
source of truth and generate the constraint from it.

**Indexes to add while the schema is being written** — the audit found only one index
existed, and none on the hottest foreign key:

```sql
CREATE INDEX ON hazel.documents (case_id, created_at DESC);   -- absent today; filters 5 queries
CREATE INDEX ON hazel.onboarding_cases (org_id);
CREATE INDEX ON hazel.review_clarifications (case_id, requested_at DESC);  -- the one existing index
```

**Drop `risk_answers`.** The audit established it is created and deleted from (`dev.py:124`)
but never inserted into or selected from — the real answers live in Coverbase. Carrying a
dead table into a production schema institutionalizes the confusion. If it is wanted later it
can be added deliberately.

### 2.3 `case_decisions` — the append-only record

```sql
CREATE TABLE hazel.case_decisions (
    id           bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    org_id       uuid        NOT NULL REFERENCES hazel.organizations(id),
    case_id      text        NOT NULL REFERENCES hazel.onboarding_cases(id),
    decided_at   timestamptz NOT NULL DEFAULT now(),
    decided_by   text        NOT NULL,
    decision     text        NOT NULL,
    from_stage   text,
    to_stage     text,
    rationale    text        NOT NULL DEFAULT '',
    payload      jsonb       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX ON hazel.case_decisions (case_id, decided_at DESC);
```

Note it does **not** cascade on case delete — that is the point of a decision record.

### 2.4 Append-only enforcement

Because the owner ignores revocations (§1.3), use a trigger:

```sql
CREATE OR REPLACE FUNCTION hazel.deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'hazel.% is append-only; % is not permitted', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END $$;

CREATE TRIGGER case_decisions_append_only
    BEFORE UPDATE OR DELETE ON hazel.case_decisions
    FOR EACH ROW EXECUTE FUNCTION hazel.deny_mutation();
```

`TRUNCATE` needs a separate `BEFORE TRUNCATE ... FOR EACH STATEMENT` trigger if that is a
concern.

### 2.5 Row-level security

```sql
ALTER TABLE hazel.onboarding_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel.onboarding_cases FORCE  ROW LEVEL SECURITY;

CREATE POLICY org_isolation ON hazel.onboarding_cases
    USING       (org_id = current_setting('app.org_id', true)::uuid)
    WITH CHECK  (org_id = current_setting('app.org_id', true)::uuid);
```

Repeat for all seven tables. Points that matter:

- `WITH CHECK` as well as `USING` — otherwise the policy filters reads but permits writing
  rows belonging to another org.
- The `true` second argument to `current_setting` makes it return NULL rather than error when
  unset; combined with `= NULL` evaluating to NULL, an unset GUC yields **zero rows** rather
  than all rows. That is the correct fail-closed direction, but it means a forgotten `SET`
  surfaces as mysterious emptiness — worth a startup assertion.
- The GUC is set **per transaction** with `SET LOCAL app.org_id = ...` on checkout (§4.3), so
  it cannot leak between pooled requests.

---

## 3. Three blocking changes outside the database

Each of these stops the App independently of any Postgres work.

### 3.1 `config.py` hard-fails at import without a `.env`

`backend/app/config.py:14-15` raises `RuntimeError` if `backend/.env` is absent. This runs at
**import**, before the lifespan handler, so uvicorn never starts. There is no `.env` on an
App — configuration arrives as process environment. Change to: load the file when present,
otherwise fall through to the process environment. `load_dotenv(override=False)` already gives
the environment precedence, so this is safe in both directions.

### 3.2 The frontend API base falls through to localhost when set to empty

`frontend/src/services/api.js:1`:

```js
const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
```

Same-origin serving requires `VITE_API_BASE_URL=""`, but the empty string is falsy, so `||`
selects `http://localhost:8000` and every request in the deployed App goes to the user's own
machine. Needs `??`, or an explicit `undefined` check. This fails only in the browser, with
no server-side signal — it will look like a total API outage.

### 3.3 `dist/` is gitignored

`.gitignore:3` ignores `dist/`. Apps does not run `npm run build`, so the bundle must be in
the source tree: un-ignore `frontend/dist/`, build with `VITE_API_BASE_URL=""`, and commit.
Add a release step so the bundle cannot silently drift from the source.

### 3.4 Import path

The backend uses absolute imports (`from app.config import ...`) rooted at `backend/`. Rather
than depending on how Apps resolves a relative `PYTHONPATH`, add a root-level `main.py` that
makes it deterministic:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))
from app.main import app  # noqa: E402,F401
```

`command` then references `main:app` (§5).

---

## 4. Connection pooling with per-connection token rotation

### 4.1 The failure being designed against

The Lakebase OAuth token *is* the Postgres password, and it expires after ~60 minutes.
Authentication happens at connect time, so a token minted once at startup produces a
deployment that is **green for an hour and then fails** — existing connections keep working
while every new one is rejected, so the symptom is intermittent errors that worsen as the
pool churns, not a clean outage. This is the single most important thing to get right and
the hardest to notice in testing.

The fix is a connect-time hook, not a refresh loop.

### 4.2 Shape

```python
import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from databricks.sdk import WorkspaceClient
from sqlalchemy import create_engine, event

_w = WorkspaceClient()
_lock = threading.Lock()
_cached: tuple[str, datetime] | None = None

TOKEN_TTL = timedelta(minutes=50)   # under the ~60 min expiry, with margin

def _credential() -> str:
    """Return a valid token, minting a new one when the cached one is near expiry."""
    global _cached
    with _lock:
        now = datetime.now(timezone.utc)
        if _cached and _cached[1] > now:
            return _cached[0]
        cred = _w.database.generate_database_credential(
            request_id=str(uuid4()), instance_names=[PG_INSTANCE]
        )
        _cached = (cred.token, now + TOKEN_TTL)
        logger.info("[lakebase] minted credential fp=%s", _fingerprint(_cached[0]))
        return _cached[0]

engine = create_engine(
    f"postgresql+psycopg://{CLIENT_ID}@{PG_HOST}:5432/{PG_DATABASE}?sslmode=require",
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
    pool_recycle=1800,        # retire connections well inside the token lifetime
)

@event.listens_for(engine, "do_connect")
def _inject_token(dialect, conn_rec, cargs, cparams):
    cparams["password"] = _credential()   # evaluated per physical connection
    return None                            # let SQLAlchemy proceed with the connect
```

Why each part is there:

- **`do_connect`** fires for every *physical* connection, including pool refills and
  reconnects after a server-side drop. This is what makes rotation automatic rather than
  scheduled.
- **The TTL cache** avoids one control-plane call per connection while guaranteeing the token
  handed out is never near expiry. The lock keeps concurrent checkouts from minting a burst.
- **`pool_recycle=1800`** bounds how long a connection can persist, so the pool cannot fill
  with connections authenticated under credentials the server has since invalidated.
- **`pool_pre_ping`** turns a dead connection into a transparent reconnect (which re-enters
  `do_connect` and gets a fresh token) rather than an error surfaced to the user.
- **`_fingerprint`** is a truncated hash — never log the token.

`pool_size=5` with `max_overflow=5` against one worker: uvicorn's threadpool default is 40,
so 10 is a deliberate cap, not a match. Raise it only if §8 shows checkout waits.

### 4.3 Replacing `connection()`

`db.py:29-39` becomes a pool checkout that also establishes the RLS context. Every call site
keeps the `with connection() as conn:` shape, so this is the one change that does *not*
ripple:

```python
@contextmanager
def connection():
    with engine.connect() as conn:          # rolls back on exception (fixes [C-16])
        with conn.begin():
            conn.exec_driver_sql("SET LOCAL app.org_id = %s", (current_org_id(),))
            yield conn
```

`SET LOCAL` is transaction-scoped, so the value cannot leak to the next request that borrows
the same pooled connection — which is exactly the bug a session-scoped `SET` would create.

---

## 5. `app.yaml` and root `requirements.txt`

### 5.1 `app.yaml`

```yaml
command:
  - "uvicorn"
  - "main:app"
  - "--host"
  - "0.0.0.0"

env:
  - name: "COVERBASE_MODE"
    value: "mock"
  - name: "COVERBASE_BASE_URL"
    value: "https://api.coverbase.example"
  - name: "COVERBASE_QUESTIONNAIRE_ID"
    value: "<questionnaire-id>"
  - name: "UPLOAD_DIR"
    value: "/Volumes/hazel/onboarding/uploads"
  - name: "HAZEL_DEV_MODE"
    value: "false"
  - name: "PG_INSTANCE"
    value: "<lakebase-instance-name>"
  - name: "PG_HOST"
    value: "<instance>.database.cloud.databricks.com"
  - name: "PG_DATABASE"
    value: "hazel_hop"
```

Three things about this file:

- **No `--port`.** The `command` array is exec'd without a shell, so `"--port"`, `"$UVICORN_PORT"`
  would pass the literal string `$UVICORN_PORT` to uvicorn and fail to parse. Uvicorn reads
  `UVICORN_PORT` from the environment on its own, which Apps sets to the same value as
  `DATABRICKS_APP_PORT`.
- **No `--workers`.** The default of 1 is what we want, and §6 explains why it is load-bearing
  rather than incidental.
- `COVERBASE_BASE_URL` is set even though the mode is mock, because `config.py:42-43` treats
  it as fatal in both modes.

The Lakebase instance and the Volume are attached as **app resources** in the App
configuration, not as raw env vars. Confirm the resource key names and the injected
credential variables against the workspace on first deploy rather than assuming them — that
is step 3 of §8.

**Answered on first deploy (2026-08-12).** The resource injects **five** variables, not six:
`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGSSLMODE`. It does **not** inject
`ENDPOINT_NAME`, so `app.yaml` sets that one explicitly. A deploy without it failed in the
lifespan with `missing ['ENDPOINT_NAME']` — and because `resolve_settings()` reports every
missing name at once, that same error is the proof the other five do arrive. The value is
the resource *name*, `projects/hazel-hop-lakebase/branches/production/endpoints/primary`, not
the UID form the console URL uses.

### 5.2 Root `requirements.txt`

Apps reads `requirements.txt` from the **repo root**; the existing one is at `backend/`.

`pydantic` is added because the code imports it directly (`schemas/cases.py`) while relying on
FastAPI to pull it in transitively — fine locally, fragile as a deployment contract.

**Superseded — do not copy the range specifiers this section originally proposed.**
`databricks-sdk>=0.30` shipped, and the container resolved an SDK with no
`WorkspaceClient.postgres`; credential minting then died four frames inside SQLAlchemy's pool.
A range specifier in a deployment artifact is a future `AttributeError` with a delayed fuse.

The live file is [`requirements.txt`](../requirements.txt) at the repo root: every version an
exact `==` pin, 9 direct plus the 25-package transitive closure, verified closed by a
clean-venv `pip install` → `pip freeze` round-trip that reproduces the file at 34 packages.
Refresh it by re-freezing wholesale; do not relax a pin to resolve an install failure.
`assert_sdk_capabilities()` in `app/lakebase.py` now fails at startup, naming the installed
version, if the SDK cannot mint Autoscaling credentials.

---

## 6. Worker count, and why

**One worker.**

This is not a sizing preference. `_pending_questionnaire_saves` (`coverbase.py:123`) is a
cross-request mutex held in process memory: incremented before a Risk-Question save
(`coverbase.py:1300-1302`), decremented after (`coverbase.py:1308-1312`), and checked at
`coverbase.py:1171` to reject a final submission while a save is still in flight.

The check at 1171 runs **unconditionally — it guards live mode as well as mock**. With two
workers, a save routed to worker A and a submit routed to worker B never observe each other's
counter. The guard passes, and the questionnaire is submitted mid-write. That is silent data
corruption in the one operation the application treats as irreversible, and no amount of
retry logic detects it.

Five further singleton fields (`coverbase.py:116-122`) hold all mock session state; they cost
durability rather than correctness, and per the decision on record they are accepted as-is.

**Sizing:** Medium (2 vCPU / 6 GB) is sufficient for one uvicorn worker. Leave horizontal
scaling (Beta) **off** — enabling it reintroduces the same bug across replicas, where it is
even harder to observe.

**Consequence to plan around.** One worker plus synchronous database calls inside `async def`
handlers means every query blocks the event loop for the whole App — with SQLite this was a
local file read; against Lakebase it is a network round trip. The affected handlers include
`upload_document`, `sync_hazel_document` and `build_hazel_review_payload`, the last of which
the frontend polls every 10–30 seconds. **Convert the DB-only handlers from `async def` to
`def`**; FastAPI then runs them in its threadpool automatically, which restores concurrency
without touching their bodies. Handlers that genuinely `await` Coverbase should keep `async`
and wrap their DB work in `run_in_threadpool`.

---

## 7. Uploads on a Unity Catalog Volume

`UPLOAD_DIR` already accepts an absolute path and only re-anchors relative ones
(`cases.py:39-41`), so the primary approach is configuration: point it at
`/Volumes/hazel/onboarding/uploads`.

This works because the code's use of the filesystem is unusually narrow — across all seven
write sites it does only `write_bytes`, `read_bytes`, `unlink` and `mkdir`. No random access,
no rename, no append, no `tempfile`. That is within the supported Volume FUSE subset.

Two things to verify on first deploy, and one to fix:

- **`cases.py:699` calls `UPLOAD_DIR.mkdir(parents=True, exist_ok=True)` on every upload.**
  Against a Volume path this is at best wasted work and at worst an error on a root that
  cannot be created. Hoist it to startup, or drop it once the Volume is known to exist.
- **`db.py:31` does the same for the database directory** — delete it outright with SQLite
  gone.
- **`cases.py:752` joins the raw `stored_name` from the database**, while every other site
  re-basenames it with `Path(...).name` (`cases.py:173`, `228`, `dev.py:135`). Harmless today
  because the value is always generated, but make it consistent while the file is open.

**Fallback.** If FUSE behaviour disappoints — throughput, or `unlink` semantics — introduce a
small storage interface with `write(name, bytes)`, `read(name)`, `delete(name)` and back it
with the Files API. That is five call sites and one seam, and it is worth defining the seam
now even if the FUSE path is what ships.

---

## 8. Verification sequence

Ordered so each step's failure is unambiguous.

1. **Grants.** As the app role: `CREATE TABLE hazel._probe(x int); DROP TABLE hazel._probe;`
   If this fails, §1.2 step 3 is missing. Then confirm `ALTER DEFAULT PRIVILEGES` took, by
   creating a table as the migration role and selecting from it as the app role.
2. **Migrations.** Apply, then verify: seven tables present, `risk_answers` absent, every
   `*_at` column `timestamptz` (`information_schema.columns`), `org_id` NOT NULL everywhere,
   and `relrowsecurity` **and** `relforcerowsecurity` both true in `pg_class` for all seven.
3. **Resources.** Deploy, and confirm the injected Lakebase and Volume variables match what
   §5.1 assumes — do not assume the names.
4. **Boot.** App reaches running. Logs show `init_db`/migrations completing once, no
   `RuntimeError` about a missing `.env` (§3.1).
5. **API.** `GET /api/health` returns `{"status":"ok","coverbase_mode":"mock"}`. Extend it to
   also report database connectivity and the age of the current credential — it is the probe
   step 9 depends on.
6. **Static and SPA.** `GET /` serves the bundle. `GET /case/HAZEL-TEST-001/documents`
   **directly, not via client-side navigation** returns `index.html` (this is the deep-link
   case `BrowserRouter` cannot handle alone). `GET /api/nonexistent` returns a JSON 404, **not**
   `index.html` — that is the proof the catch-all does not shadow `/api/*`.
7. **Browser origin check.** With devtools open, confirm requests go to the App origin and
   not `localhost:8000` (§3.2). This is the failure that no server-side test can catch.
8. **Full case walkthrough.** Submit interest → NDA accept → institution profile → **document
   upload** (verify the object lands in the Volume and `documents.file_sha256` is populated) →
   due diligence → risk questions → review. Then re-check RLS by setting `app.org_id` to a
   different UUID in a `psql` session and confirming zero rows.
9. **Restart durability.** Restart the App, reload a case. Stage, profile, documents and
   clarifications must all survive. Mock risk-question answers will **not** — that is the
   accepted §10.1 shortcut, and confirming it here keeps it a known property rather than a
   future bug report.

### 8.1 Proving token rotation specifically

This is the one failure that appears an hour after a green deploy, so it needs a test that
compresses the clock rather than waiting for it.

1. Log a **fingerprint** — `sha256(token)[:8]`, never the token — at each mint (§4.2) and at
   each physical connect.
2. Temporarily set `pool_recycle=120` and `TOKEN_TTL=90s`, and deploy.
3. Drive steady traffic against a read endpoint for ~10 minutes, i.e. several multiples of
   both intervals.
4. **Pass criteria, all three:** the fingerprint changes at least twice in the log; every
   request returns 200 across the changes; and `pg_stat_activity.backend_start` for the app
   role shows connections genuinely re-established rather than one long-lived session
   masking the whole test.
5. Restore the real values (`pool_recycle=1800`, `TOKEN_TTL=50m`).
6. Then run one **soak past the 60-minute mark** with light periodic traffic. Step 4 proves
   the mechanism; only this proves the real expiry boundary. Do not skip it — the compressed
   test cannot detect a wrong assumption about the actual token lifetime.

A useful negative control: pin the token once at startup and confirm the soak *fails*. If it
passes, the test is not exercising what it claims to.

---

## 9. In-memory state that breaks with more than one worker

Consolidated from `schema-audit.md` §5.2. All of it lives on the module-level singleton
`coverbase_service = CoverbaseService()` (`coverbase.py:1696`), instantiated at import, with
fields declared at `coverbase.py:116-123`.

**Correctness break — the reason workers are pinned to 1:**

- `_pending_questionnaire_saves` (declared 123, checked 1171, mutated 1300-1312). Detailed in
  §6. Mode-independent: it guards live mode too. Also leaks a permanent "pending" state if
  the process dies between increment and decrement, which no restart clears because the
  counter never existed anywhere durable.

**Durability breaks — lost on any restart or redeploy, invisible across workers:**

- `_mock_questionnaire_response_overrides` (120-122) — every mock risk-question answer.
- `_mock_session_statuses` (119) — a submitted session reverts to `open`.
- `_mock_selected_use_cases` (116) — when empty, `_mock_ai_generated_followups` returns `[]`
  (583-584), sending the caller into the 20 × 2 s poll loop at 698-713: a **40-second stall**
  on every pre-existing session after a restart.
- `_mock_document_ids` (117) — mock attachments vanish.
- `_mock_documents` (118) — a missing entry raises `RuntimeError` at 558.

These diverge from the database, which persists `coverbase_session_id` across restarts. After
a restart the row points at a session the service knows nothing about — so the failure
presents as corrupt data rather than as empty state.

**Nothing else in the codebase holds mutable process state.** No threads, no
`asyncio.create_task`, no `BackgroundTasks`, no queue, no cache, no rate limiter, no
WebSocket registry, no session store. Everything else at module level is a read-only constant.
The blast radius is genuinely this one file.

---

## 10. Shortcuts that survive into the seed, and the cost of undoing each

`org_id`, `timestamptz`, the decision record and RLS are all **in** this port, per the
decision on record. What follows is what is still deferred. Ordered by cost to undo.

### 10.1 Workers pinned to 1 — *moderate*

Cause: §9. Undo: move the six dicts into Postgres and turn the mutex at `coverbase.py:1171`
into a row lock (`SELECT ... FOR UPDATE`). Roughly 15 branch sites inside an otherwise
untouched 1,697-line file, plus three small tables. Nothing else in the application blocks
horizontal scaling, so this is the *entire* cost of that capability — but until it is paid,
turning scaling on silently reintroduces the submit-mid-write bug.

### 10.2 No identity or authorization model — *large; the biggest remaining item*

Apps guarantees every caller has a Databricks identity, but the application has no user, org,
or permission concept: `requested_by` is free text (`db.py:114`) and no endpoint checks who
is calling. So `org_id` will be a single hardcoded demo org and `SET LOCAL app.org_id` will
set a constant. **The RLS machinery will be correct and load-bearing on exactly one value.**

Undo: map the forwarded identity to an org membership, resolve it per request, and feed it to
the GUC. The RLS policies themselves need no change — that is precisely what §2.5 buys — but
the identity subsystem is net-new: user and membership tables, request-scoped resolution,
and an authorization check on every endpoint. Worth stating plainly that a single-org RLS
deployment is *not* evidence that multi-tenancy works; it has never been exercised with two
values.

### 10.3 `init_db()` still runs DDL at startup as the table owner — *small*

The app role owns its tables, which is why §1.3's `FORCE ROW LEVEL SECURITY` and the §2.4
trigger are necessary at all. Undo: a separate migration role owning the schema, with the app
role holding DML only — at which point `FORCE` becomes belt-and-braces instead of essential.
The `ALTER DEFAULT PRIVILEGES` grants in §1.2 exist to make this split cheap later; that is
their main purpose.

### 10.4 `/api/dev/*` is reachable in production — *trivial, but easy to forget*

`POST /api/dev/create-case` and `POST /api/dev/reset-case` are gated **only** by the
`^HAZEL-TEST-[A-Za-z0-9_-]+$` regex (`dev.py:16`) — **not** by `HAZEL_DEV_MODE` (`dev.py:17`),
which gates only the clarification endpoint. `reset-case` deletes documents, clarifications
and risk answers and rewinds the stage (`dev.py:103-124`). Any authenticated Databricks user
can call it against any case whose ID matches the pattern. Undo: one dependency on the
router. Do it in this pass if the seed will hold anything real.

### 10.5 Logical operations still span multiple transactions — *moderate*

`sync_hazel_document` opens four (`cases.py:194, 235, 241, 289`);
`upload_clarification_document` three. A failure between them leaves partial state — and in
`delete_document` the transaction commits at `cases.py:751` before the file is unlinked at 752
and before the Coverbase call that can raise 502 at 768, so the row and the file are already
gone when the client sees the error. Undo: thread one connection through each operation.
Mechanical but touches the most intricate code in the file.

### 10.6 No pagination — *small, but it degrades silently*

`GET /documents` (`cases.py:674`), the clarification history (`cases.py:103`) and the review
payload return unbounded result sets. Fine at demo volume; it worsens gradually and will be
misdiagnosed as a Lakebase problem.

### 10.7 Coverbase clarification sync does not exist — *upstream, not ours*

`review_clarifications.coverbase_sync_status` is permanently `'pending_integration'`
(`cases.py:1151-1156`), and the review payload advertises
`"coverbase_clarification_sync_supported": False` (`cases.py:1025`). This is a documented gap
in the Coverbase API (`models/clarifications.py:1-6`), not a shortcut taken here — recorded
so it is not later mistaken for one.
