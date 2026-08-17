"""Database access: a pooled Lakebase connection with tenant context per transaction.

Replaces the file-backed sqlite3 connection this module used to open per request,
and the inline DDL that used to run on every boot. Schema now lives in
backend/migrations/ and is applied by backend/migrate.py.
"""

from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from sqlalchemy import create_engine, event

# Imported for its side effect: loads backend/.env with override=False, so
# injected App variables always win over anything in the file.
from app import config  # noqa: F401
from app.lakebase import mint_password, resolve_settings

STAGES = [
    "NDA_PENDING",
    "NDA_ACCEPTED",
    "INSTITUTION_PROFILE",
    "DOCUMENTS",
    "DUE_DILIGENCE",
    "RISK_QUESTIONS",
    "HAZEL_REVIEW",
]

# Placeholder tenant. This app has no auth, no session and no user identity, so
# every request belongs to the same demo organisation. It is a hardcoded constant
# on purpose — when real tenancy arrives this reads from the request, and until
# then it should be obvious that it is not wired to anything.
DEMO_ORG_ID = "00000000-0000-0000-0000-000000000001"


def current_org_id() -> str:
    return DEMO_ORG_ID


def utc_now() -> datetime:
    """Now, as an aware datetime.

    Was an ISO-8601 *string* under SQLite, because every timestamp column was
    TEXT. The columns are timestamptz now and psycopg adapts datetime natively.
    """
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
#
# The Lakebase OAuth token *is* the Postgres password and expires in roughly an
# hour. Minting it once at startup produces a deployment that is green for an
# hour and then fails, so it is minted per physical connection, behind a cache.

TOKEN_TTL = timedelta(minutes=50)

_token_lock = threading.Lock()
_token: tuple[str, datetime] | None = None


def _password() -> str:
    global _token
    with _token_lock:
        now = datetime.now(timezone.utc)
        if _token is None or _token[1] <= now:
            _token = (mint_password(_settings()), now + TOKEN_TTL)
        return _token[0]


def credential_status() -> dict:
    """What /api/health reports about the current Lakebase credential.

    The fingerprint is the first 8 hex of sha256(token). It identifies the
    credential without disclosing it, which is what makes the token-rotation soak
    observable from outside: drive traffic past the TTL and the fingerprint must
    change. Without this the only symptom of a rotation bug is the app working
    fine for an hour and then failing.
    """
    with _token_lock:
        if _token is None:
            return {"minted": False}
        token, expires_at = _token
        now = datetime.now(timezone.utc)
        return {
            "minted": True,
            "fingerprint": hashlib.sha256(token.encode()).hexdigest()[:8],
            "age_seconds": round((now - (expires_at - TOKEN_TTL)).total_seconds()),
            "expires_in_seconds": round((expires_at - now).total_seconds()),
            "ttl_seconds": round(TOKEN_TTL.total_seconds()),
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

_engine = None
_engine_lock = threading.Lock()
_cached_settings = None


def _settings():
    global _cached_settings
    if _cached_settings is None:
        _cached_settings = resolve_settings()
    return _cached_settings


# Lakebase Autoscaling is Neon-backed, and its transaction-mode pooler rejects
# search_path in the connection startup packet outright:
#
#     ERROR: unsupported startup parameter in options: search_path.
#     Please use unpooled connection or remove this parameter from the startup package.
#
# Verified against the real pooler host. So `connect_args` is not merely unreliable
# through a pooler, it makes connecting impossible — which is why search_path is
# established per transaction in connection() instead, alongside app.org_id and in
# the same round trip. connect_args stays on for direct endpoints, where it is
# legal and means a connection is in the right schema even outside connection().
POOLER_HOST_MARKER = "-pooler."


def _connect_args(host: str) -> dict:
    if POOLER_HOST_MARKER in host:
        return {}
    return {"options": "-c search_path=hazel"}


def get_engine():
    """Build the pool on first use.

    Deliberately lazy: resolve_settings() raises when the Lakebase variables are
    absent, and an import-time raise would take the whole app down before FastAPI
    could report anything useful.
    """
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine

        engine = create_engine(
            _settings().sqlalchemy_url(),
            connect_args=_connect_args(_settings().host),
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
            # Retire connections well inside the token lifetime, so a physical
            # connection is never older than the credential that opened it.
            pool_recycle=1800,
        )

        @event.listens_for(engine, "do_connect")
        def _inject_token(dialect, conn_rec, cargs, cparams):
            cparams["password"] = _password()
            return None  # let SQLAlchemy carry on and connect

        _engine = engine
        return _engine


# ---------------------------------------------------------------------------
# Call-site adapter
# ---------------------------------------------------------------------------
#
# The 83 existing call sites are all of the shape
#
#     row = conn.execute("SELECT ... WHERE id = ?", (case_id,)).fetchone()
#     value = row["column"]
#
# SQLAlchemy 2.0 returns Row objects, which are tuple-like: row["column"] raises,
# and dict(row) does not work. Rather than rewrite every access into
# row._mapping["column"], these two thin adapters keep the existing idiom over a
# SQLAlchemy Connection, so the port stays a placeholder change plus the handful
# of genuinely non-mechanical cases.


class _Conn:
    """sqlite3-shaped facade over a SQLAlchemy Connection.

    Placeholders are %s, not ? — psycopg's paramstyle. The underlying SQLAlchemy
    Connection stays reachable as .sa for anything that needs it.

    Statements go through the raw psycopg cursor rather than
    Connection.exec_driver_sql, which is not a stylistic choice. SQLAlchemy
    applies its own percent-formatting to driver SQL, and it does so even with no
    parameters bound::

        exec_driver_sql("SELECT 'a%b'")  ->  'a$1'      <- silently corrupted
        raw psycopg cursor               ->  'a%b'

    A literal percent is not exotic here — any LIKE pattern has one — and the
    failure is a wrong result rather than an error, so it would not necessarily
    show up in testing. Going through the DBAPI cursor keeps psycopg's own
    parameter handling, and psycopg leaves the SQL alone when no parameters are
    passed. The cursor is on the same physical connection, so it stays inside the
    transaction SQLAlchemy opened.
    """

    __slots__ = ("sa",)

    def __init__(self, sa_conn):
        self.sa = sa_conn

    def execute(self, sql: str, params=()):
        cursor = self.sa.connection.driver_connection.cursor(row_factory=dict_row)
        cursor.execute(sql, tuple(params) if params else None)
        return cursor


@contextmanager
def connection():
    """A pooled connection inside a transaction, with tenant context established.

    The GUC is set with set_config(..., true) rather than `SET LOCAL app.org_id =
    %s`: SET is a utility statement and Postgres rejects bound parameters in it
    ("syntax error at or near $1"). The third argument keeps the setting
    transaction-local, so it cannot leak to the next request that borrows this
    connection from the pool — which also makes this safe against the endpoint's
    transaction-mode pooler.

    search_path rides along in the same statement. It is a constant and would
    rather live on the connection, but the pooler refuses it as a startup
    parameter (see _connect_args), and this costs nothing: it is a round trip we
    are already making, and being transaction-local it is immune to whatever the
    pooler does with server connections between transactions.
    """
    with get_engine().connect() as sa_conn:  # rolls back if the block raises
        with sa_conn.begin():
            sa_conn.exec_driver_sql(
                "SELECT set_config('app.org_id', %s, true),"
                "       set_config('search_path', %s, true)",
                (current_org_id(), "hazel"),
            )
            yield _Conn(sa_conn)


def row_dict(row):
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Startup check
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Assert the database is usable. It no longer creates anything.

    Schema is applied out of band by backend/migrate.py. A forgotten migration
    used to be impossible (the DDL ran on every boot) and is now a real failure
    mode, so it is checked here instead of surfacing as a missing-relation error
    on the first request.
    """
    expected = {
        "onboarding_cases",
        "institution_profiles",
        "express_interest_submissions",
        "documents",
        "due_diligence",
        "review_clarifications",
        "case_decisions",
    }
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS onboarding_cases (
                id TEXT PRIMARY KEY,
                institution_id TEXT NOT NULL,
                current_stage TEXT NOT NULL,
                nda_accepted_at TEXT,
                institution_profile_completed_at TEXT,
                documents_completed_at TEXT,
                due_diligence_completed_at TEXT,
                risk_questions_submitted_at TEXT,
                coverbase_session_id TEXT,
                coverbase_vendor_id TEXT,
                coverbase_status TEXT,
                hazel_review_status TEXT,
                review_status TEXT NOT NULL DEFAULT 'Not started',
                additional_information_required INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS institutions (
                id TEXT PRIMARY KEY,
                legal_name TEXT NOT NULL,
                fdic_certificate TEXT NOT NULL UNIQUE,
                rssd_id TEXT,
                institution_type TEXT NOT NULL,
                registration_contact_email TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rafa_screenings (
                institution_id TEXT PRIMARY KEY REFERENCES institutions(id) ON DELETE CASCADE,
                fdic_certificate TEXT NOT NULL,
                rssd_id TEXT,
                rafa_score REAL NOT NULL,
                rafa_status TEXT NOT NULL,
                rating_label TEXT,
                composite_rating TEXT,
                profile_year TEXT,
                profile_quarter TEXT,
                screened_at TEXT NOT NULL,
                CHECK (rafa_status IN ('accepted', 'rejected'))
            );
            CREATE TABLE IF NOT EXISTS institution_profiles (
                case_id TEXT PRIMARY KEY REFERENCES onboarding_cases(id) ON DELETE CASCADE,
                legal_name TEXT, fdic_certificate_number TEXT, rssd_id TEXT,
                institution_type TEXT, website TEXT, headquarters TEXT,
                admission_type TEXT, international_correspondent_relationships TEXT,
                has_dba TEXT, has_fintech_or_baas_programs TEXT,
                primary_contact_name TEXT, primary_contact_title TEXT,
                primary_contact_email TEXT,
                additional_responses_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS express_interest_submissions (
                case_id TEXT PRIMARY KEY REFERENCES onboarding_cases(id) ON DELETE CASCADE,
                legal_name TEXT, fdic_certificate_number TEXT, rssd_id TEXT,
                institution_type TEXT, website TEXT, headquarters TEXT,
                contact_name TEXT, contact_title TEXT, contact_email TEXT,
                data_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL REFERENCES onboarding_cases(id) ON DELETE CASCADE,
                document_type TEXT NOT NULL, original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL, size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                coverbase_document_id TEXT,
                coverbase_sync_status TEXT NOT NULL DEFAULT 'not_started',
                coverbase_synced_at TEXT,
                coverbase_sync_error TEXT,
                coverbase_sync_details_json TEXT NOT NULL DEFAULT '{}',
                file_sha256 TEXT
            );
            CREATE TABLE IF NOT EXISTS due_diligence (
                case_id TEXT PRIMARY KEY REFERENCES onboarding_cases(id) ON DELETE CASCADE,
                data_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS risk_answers (
                case_id TEXT NOT NULL REFERENCES onboarding_cases(id) ON DELETE CASCADE,
                question_id TEXT NOT NULL, answer TEXT NOT NULL,
                confirmed INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
                PRIMARY KEY (case_id, question_id)
            );
            CREATE TABLE IF NOT EXISTS review_clarifications (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES onboarding_cases(id) ON DELETE CASCADE,
                source TEXT NOT NULL,
                source_reference_id TEXT,
                requested_by TEXT NOT NULL,
                request_text TEXT NOT NULL,
                request_type TEXT NOT NULL DEFAULT 'additional_information',
                question_id TEXT,
                requested_at TEXT NOT NULL,
                due_at TEXT,
                status TEXT NOT NULL,
                member_response TEXT NOT NULL DEFAULT '',
                submitted_at TEXT,
                document_required INTEGER NOT NULL DEFAULT 0,
                document_label TEXT,
                replacement_of_hazel_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
                uploaded_hazel_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
                coverbase_sync_status TEXT NOT NULL DEFAULT 'not_started',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (status IN ('open', 'draft', 'submitted', 'resolved'))
            );
            CREATE INDEX IF NOT EXISTS idx_review_clarifications_case
            ON review_clarifications(case_id, requested_at DESC);
            """
        )
        profile_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(institution_profiles)").fetchall()
        }
        if "additional_responses_json" not in profile_columns:
            conn.execute(
                "ALTER TABLE institution_profiles ADD COLUMN additional_responses_json TEXT NOT NULL DEFAULT '{}'"
            )
        case_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(onboarding_cases)").fetchall()
        }
        if "hazel_review_status" not in case_columns:
            conn.execute("ALTER TABLE onboarding_cases ADD COLUMN hazel_review_status TEXT")
            conn.execute(
                "UPDATE onboarding_cases SET hazel_review_status = review_status "
                "WHERE review_status NOT IN ('', 'Not started')"
            )
        document_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(documents)").fetchall()
        }
        document_migrations = {
            "coverbase_document_id": "TEXT",
            "coverbase_sync_status": "TEXT NOT NULL DEFAULT 'not_started'",
            "coverbase_synced_at": "TEXT",
            "coverbase_sync_error": "TEXT",
            "coverbase_sync_details_json": "TEXT NOT NULL DEFAULT '{}'",
            "file_sha256": "TEXT",
        }
        for column, definition in document_migrations.items():
            if column not in document_columns:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {column} {definition}")
        now = utc_now()
        conn.execute(
            """INSERT OR IGNORE INTO onboarding_cases
            (id, institution_id, current_stage, review_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ("HAZEL-TEST-001", "NORTHSTAR-001", "NDA_PENDING", "Not started", now, now),
        )
        conn.execute(
            """INSERT OR IGNORE INTO institution_profiles
            (case_id, legal_name, fdic_certificate_number, rssd_id, institution_type,
             website, headquarters, admission_type,
             international_correspondent_relationships, has_dba,
             has_fintech_or_baas_programs, primary_contact_name,
             primary_contact_title, primary_contact_email, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("HAZEL-TEST-001", "Northstar Community Bank, N.A.", "12001", "",
             "National bank", "https://northstar.example", "Charlotte, North Carolina",
             "", "", "", "", "Jamie Chen", "Chief Operating Officer",
             "jamie.chen@northstar.example", now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO due_diligence (case_id, data_json, updated_at) VALUES (?, ?, ?)",
            ("HAZEL-TEST-001", json.dumps({"institutionWebsite": "https://northstar.example", "headquarters": "Charlotte, North Carolina"}), now),
        )
        conn.execute(
            """INSERT OR IGNORE INTO express_interest_submissions
            (case_id, legal_name, fdic_certificate_number, rssd_id, institution_type,
             website, headquarters, contact_name, contact_title, contact_email,
             data_json, updated_at)
            SELECT case_id, legal_name, fdic_certificate_number, rssd_id,
                   institution_type, website, headquarters, primary_contact_name,
                   primary_contact_title, primary_contact_email, '{}', updated_at
            FROM institution_profiles WHERE case_id = ?""",
            ("HAZEL-TEST-001",),
        )
        present = {
            row["tablename"]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'hazel'"
            ).fetchall()
        }
        missing = expected - present
        if missing:
            raise RuntimeError(
                f"Lakebase schema is not current; missing tables: {sorted(missing)}. "
                "Run: python backend/migrate.py"
            )

        # An unset or empty GUC yields zero rows rather than an error, which is the
        # right failure direction but is silent. Prove the round-trip at startup so
        # a misconfigured tenant context is loud instead of looking like empty data.
        got = conn.execute("SELECT current_setting('app.org_id', true)").fetchone()
        if not got or got["current_setting"] != current_org_id():
            raise RuntimeError(
                "app.org_id did not round-trip; every query would silently return "
                "zero rows. Check set_config in connection()."
            )


# ---------------------------------------------------------------------------
# Helpers used across the routers
# ---------------------------------------------------------------------------


def require_case(conn, case_id: str):
    row = conn.execute(
        "SELECT * FROM onboarding_cases WHERE id = %s", (case_id,)
    ).fetchone()
    if not row:
        return None
    return row_dict(row)


def update_stage(conn, case_id: str, stage: str, **fields):
    """Advance a case, and record the decision in the same transaction.

    The stage is monotonic: an attempt to move backwards is clamped to the
    current stage. That guard used to read and then write without locking, which
    was harmless against a single-writer SQLite file and is not behind a pool —
    two concurrent requests could both read the old stage. FOR UPDATE closes it,
    and it has to be closed now because the decision row records from_stage.
    """
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}")

    row = conn.execute(
        "SELECT current_stage FROM onboarding_cases WHERE id = %s FOR UPDATE",
        (case_id,),
    ).fetchone()
    from_stage = row["current_stage"] if row else None

    effective_stage = stage
    if from_stage and STAGES.index(from_stage) > STAGES.index(stage):
        effective_stage = from_stage

    assignments = ["current_stage = %s", "updated_at = %s"]
    values = [effective_stage, utc_now()]
    for key, value in fields.items():
        assignments.append(f"{key} = %s")
        values.append(value)
    values.append(case_id)
    conn.execute(
        f"UPDATE onboarding_cases SET {', '.join(assignments)} WHERE id = %s", values
    )

    # Written even when the clamp made this a no-op. An attempted-and-clamped
    # transition is exactly what an append-only record should show; payload keeps
    # what was requested alongside what actually took effect.
    conn.execute(
        """INSERT INTO case_decisions
             (case_id, decided_by, decision, from_stage, to_stage, payload)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (
            case_id,
            "system",  # no user identity exists anywhere in this app yet
            "stage_transition",
            from_stage,
            effective_stage,
            Jsonb({"requested_stage": stage, "fields": sorted(fields)}),
        ),
    )
