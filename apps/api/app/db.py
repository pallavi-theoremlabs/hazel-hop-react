"""Database access: a pooled Lakebase connection with tenant context per transaction.

Replaces the file-backed sqlite3 connection this module used to open per request,
and the inline DDL that used to run on every boot. Schema now lives in
postgres setup/hazel_schema.sql and is applied out of band.
"""

from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from sqlalchemy import create_engine, event

# Imported for its side effect: loads apps/api/.env with override=False, so
# injected App variables always win over anything in the file.
from app import config  # noqa: F401
from app.lakebase import mint_password, resolve_settings
from app.tenancy import SYSTEM_SESSION, current_session

# The application role from postgres setup/hazel_schema.sql, and the reason RLS is
# worth anything here. Every p_tenant policy is written against it, and it is
# created NOLOGIN NOBYPASSRLS on purpose.
#
# Assuming the connection is already subject to those policies is how RLS gets
# tested into a false pass: the App connects as its own service principal, which
# owns nothing but is a Databricks identity, and Databricks identities carry
# rolbypassrls. Without the SET LOCAL ROLE below, every policy in the schema is
# skipped and every query returns every tenant's rows.
#
# LOCAL, so it reverts at commit and cannot leak to the next request that borrows
# this connection from the pool — the same reasoning as the set_config calls.
APP_ROLE = "hop_app"

# The ordered onboarding progression. Position is meaningful: update_stage() uses
# the index to clamp a backwards transition, so this list is a sequence and not
# merely a set of legal values.
STAGES = [
    "NDA_PENDING",
    "NDA_ACCEPTED",
    "INSTITUTION_PROFILE",
    "DOCUMENTS",
    "DUE_DILIGENCE",
    "RISK_QUESTIONS",
    "HAZEL_REVIEW",
]

# Stages that are an outcome rather than a step. A case in one of these is not
# partway along STAGES, it is finished, so these are deliberately kept out of the
# list above: giving INQUIRY_REJECTED an index would make it comparable to
# DOCUMENTS under the clamp, which is meaningless.
#
# Written by submit_interest() when RAFA screening rejects an institution. The
# deployed CHECK constraint does NOT cover this value, or any value in STAGES —
# see the note below.
TERMINAL_STAGES = frozenset({"INQUIRY_REJECTED"})

ALL_STAGES = frozenset(STAGES) | TERMINAL_STAGES

# NOTE: the three constants above describe the *application's* stage machine. It
# does not merely differ from ck_case_stage — the two sets are disjoint. Read from
# the live catalog, not from the schema file:
#
#     app       NDA_PENDING NDA_ACCEPTED INSTITUTION_PROFILE DOCUMENTS
#               DUE_DILIGENCE RISK_QUESTIONS HAZEL_REVIEW INQUIRY_REJECTED
#     database  INQUIRY ELIGIBILITY_SCREENING NDA RISK_ASSESSMENT
#               VANTAGE_REVIEW ACCOUNT_OPENING COMPLETED
#
# Not one value above is legal for onboarding_case.current_stage. DUE_DILIGENCE
# looks like an overlap and is not: the deployed constraint has no such stage, so
# writing it raises a check-constraint violation rather than landing in a
# neighbouring bucket. An earlier version of this note claimed three application
# stages collapsed onto a schema DUE_DILIGENCE; that stage exists only in a draft
# of hazel_schema.sql that was never applied.
#
# Which vocabulary wins is an open product decision, not something to settle here.
# The constants are left in place because update_stage() and the parked cases
# router still read them; nothing mounted today writes a stage.


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
# established per transaction in connection() instead, alongside the hop.* GUCs and in
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
def connection(session: tuple[str | None, str | None, str] | None = None):
    """A pooled connection inside a transaction, under the schema's session contract.

    `session` is (institution_id, user_id, role) and defaults to the one carried by
    the request being served. It is passed explicitly only by work running outside
    a request, such as the startup check in init_db().

    The GUCs are set with set_config(..., true) rather than `SET LOCAL hop.x = %s`:
    SET is a utility statement and Postgres rejects bound parameters in it
    ("syntax error at or near $1"). The third argument keeps each setting
    transaction-local, so none can leak to the next request that borrows this
    connection from the pool — which also makes this safe against the endpoint's
    transaction-mode pooler.

    search_path rides along in the same statement. It is a constant and would
    rather live on the connection, but the pooler refuses it as a startup
    parameter (see _connect_args), and this costs nothing: it is a round trip we
    are already making, and being transaction-local it is immune to whatever the
    pooler does with server connections between transactions.
    """
    institution_id, user_id, role = session or current_session()
    with get_engine().connect() as sa_conn:  # rolls back if the block raises
        with sa_conn.begin():
            # Role first. set_config below is harmless under any role, but the
            # statements the caller then runs are not, and a SET ROLE after them
            # would be too late.
            sa_conn.exec_driver_sql(f"SET LOCAL ROLE {APP_ROLE}")
            # The three GUCs hazel_schema.sql names as the session contract, plus
            # search_path, in one round trip. All transaction-local: current_setting
            # is what hazel.current_institution() and friends read, and the policies
            # fail closed on NULL, so a request that never set them sees nothing
            # rather than everything.
            sa_conn.exec_driver_sql(
                "SELECT set_config('hop.institution_id', %s, true),"
                "       set_config('hop.user_id', %s, true),"
                "       set_config('hop.role', %s, true),"
                "       set_config('search_path', %s, true)",
                (institution_id or "", user_id or "", role, "hazel"),
            )
            yield _Conn(sa_conn)


def row_dict(row):
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Startup check
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Assert the database is usable. It no longer creates anything.

    Schema is applied out of band from postgres setup/hazel_schema.sql. There is no
    migration runner: the file is a DROP-and-recreate script, so pointing one at it
    would make a routine command destroy the database. Apply it deliberately, with
    the tooling in postgres setup/.

    A forgotten apply used to be impossible (the DDL ran on every boot) and is now a
    real failure mode, so it is checked here instead of surfacing as a
    missing-relation error on the first request.
    """
    # The schema in postgres setup/hazel_schema.sql, which is authoritative and
    # final, and corrected against the deployed catalogs rather than the other way
    # round.
    #
    # An apps/api/migrations/ directory used to build a different, retired model. It
    # was deleted rather than left beside a working migration runner: a --status run
    # against it is what created the stray hazel.schema_migrations table in the live
    # database. Recover the old DDL from git history if the parked routers need it.
    #
    # "user", not "app_user". The deployed table is hazel."user" — bare `user` is a
    # reserved word, so every reference to it needs permanent quoting. This check
    # reads pg_tables, which reports the unquoted name, so it is spelled plainly
    # here.
    #
    # hazel_schema.sql used to declare app_user and was corrected to match the
    # database rather than the other way round. The live primary key index is still
    # named app_user_pkey, which is how the direction is known: the table was
    # created under that name and renamed, and Postgres keeps index names across a
    # rename.
    #
    # This used to accept either spelling. It no longer does. Both workspaces were
    # read directly and both have `user`, so the accommodation covered a database
    # that does not exist, and accepting a name nothing deploys would let a genuinely
    # wrong schema past this check.
    expected = {
        "institution",
        "user",
        "rafa",
        "onboarding_case",
        "document",
        "case_stage_transition",
        "audit_log",
    }

    with connection(session=SYSTEM_SESSION) as conn:
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
                "Apply apps/api/postgres setup/hazel_schema.sql."
            )

        # Prove the role took effect. This is the check that matters most, because
        # its failure mode is silent: connected as a Databricks identity without it,
        # every p_tenant policy is bypassed and every query returns every
        # institution's rows, which looks like working software.
        got = conn.execute("SELECT current_user, hazel.is_system() AS sys").fetchone()
        if got["current_user"] != APP_ROLE:
            raise RuntimeError(
                f"SET LOCAL ROLE did not take effect: connected as "
                f"{got['current_user']}, expected {APP_ROLE}. RLS would be bypassed "
                f"entirely. Grant it with: GRANT {APP_ROLE} TO \"<sp-client-id>\";"
            )
        if not got["sys"]:
            raise RuntimeError(
                "hop.role did not round-trip; the session contract from "
                "hazel_schema.sql is not established. Check set_config in connection()."
            )


# ---------------------------------------------------------------------------
# Helpers used across the routers
# ---------------------------------------------------------------------------


def require_case(conn, case_id: str):
    row = conn.execute(
        "SELECT * FROM onboarding_case WHERE id = %s", (case_id,)
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

    # A rejected inquiry has left the progression, so there is no index to compare
    # and nothing to clamp to. Checked before the index lookup below, which would
    # otherwise raise a bare ValueError from STAGES.index() naming neither the case
    # nor why it has no position.
    if from_stage in TERMINAL_STAGES:
        raise ValueError(
            f"Case {case_id} is {from_stage}, which is terminal; it cannot advance "
            f"to {stage}."
        )

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
