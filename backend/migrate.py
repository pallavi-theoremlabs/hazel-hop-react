"""Ordered migration runner for the Hazel HOP Lakebase database.

    python backend/migrate.py --status     # what is applied, what is pending
    python backend/migrate.py              # apply everything pending
    python backend/migrate.py --verify     # post-apply assertions (§8 step 2)

Connection details come from the injected Lakebase resource variables; the
password is a freshly minted OAuth token. See app/lakebase.py.

Each file is applied inside its own transaction and recorded in
hazel.schema_migrations. A file that fails rolls back whole, so a partially
applied migration is not a state this can end up in.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.lakebase import (  # noqa: E402
    assert_sdk_capabilities,
    mint_password,
    resolve_settings,
    sdk_version,
)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

TRACKING_DDL = """
CREATE SCHEMA IF NOT EXISTS hazel;
CREATE TABLE IF NOT EXISTS hazel.schema_migrations (
    filename    text        PRIMARY KEY,
    sha256      text        NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
);
"""

EXPECTED_TABLES = {
    "onboarding_cases",
    "institution_profiles",
    "express_interest_submissions",
    "documents",
    "due_diligence",
    "review_clarifications",
    "case_decisions",
}


def connect() -> psycopg.Connection:
    settings = resolve_settings()
    return psycopg.connect(
        password=mint_password(settings),
        autocommit=False,
        **settings.psycopg_kwargs(),
    )


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def applied(conn: psycopg.Connection) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT filename, sha256 FROM hazel.schema_migrations")
        return dict(cur.fetchall())


def cmd_status(conn: psycopg.Connection) -> int:
    done = applied(conn)
    drift = False
    for path in migration_files():
        recorded = done.get(path.name)
        if recorded is None:
            print(f"  pending  {path.name}")
        elif recorded != sha256(path):
            print(f"  CHANGED  {path.name}  (applied content differs from disk)")
            drift = True
        else:
            print(f"  applied  {path.name}")
    return 1 if drift else 0


def cmd_apply(conn: psycopg.Connection) -> int:
    done = applied(conn)
    pending = [p for p in migration_files() if p.name not in done]

    for path in migration_files():
        recorded = done.get(path.name)
        if recorded is not None and recorded != sha256(path):
            print(
                f"refusing to continue: {path.name} was already applied but its "
                "content has changed on disk. Add a new migration instead of "
                "editing an applied one.",
                file=sys.stderr,
            )
            return 1

    if not pending:
        print("nothing to apply")
        return 0

    for path in pending:
        print(f"applying {path.name} ...", end=" ", flush=True)
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(path.read_text(encoding="utf-8"))
                    cur.execute(
                        "INSERT INTO hazel.schema_migrations (filename, sha256) "
                        "VALUES (%s, %s)",
                        (path.name, sha256(path)),
                    )
        except Exception as exc:
            print("FAILED")
            print(f"  {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print("ok")
    return 0


def cmd_verify(conn: psycopg.Connection) -> int:
    """§8 step 2 — assert the shape the migrations were supposed to produce."""
    failures: list[str] = []

    with conn.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'hazel'"
        )
        tables = {row[0] for row in cur.fetchall()}

        present = EXPECTED_TABLES & tables
        if present != EXPECTED_TABLES:
            failures.append(f"missing tables: {sorted(EXPECTED_TABLES - tables)}")
        print(f"  seven tables present ......... {len(present)}/7")

        if "risk_answers" in tables:
            failures.append("risk_answers still exists")
        print(f"  risk_answers absent .......... {'risk_answers' not in tables}")

        cur.execute(
            """SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                 FROM pg_class c
                 JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'hazel' AND c.relname = ANY(%s)
                ORDER BY c.relname""",
            (sorted(EXPECTED_TABLES),),
        )
        for name, enabled, forced in cur.fetchall():
            ok = enabled and forced
            if not ok:
                failures.append(
                    f"{name}: relrowsecurity={enabled} relforcerowsecurity={forced}"
                )
            print(f"  RLS enabled+forced ........... {name}: {enabled}/{forced}")

        # Every policy must guard both USING and WITH CHECK with nullif(), or an
        # empty-string GUC raises 22P02 instead of returning zero rows.
        cur.execute(
            """SELECT tablename, qual, with_check
                 FROM pg_policies
                WHERE schemaname = 'hazel' AND policyname = 'org_isolation'
                ORDER BY tablename"""
        )
        rows = cur.fetchall()
        if len(rows) != len(EXPECTED_TABLES):
            failures.append(f"expected 7 org_isolation policies, found {len(rows)}")
        for name, qual, with_check in rows:
            if with_check is None:
                failures.append(f"{name}: policy has no WITH CHECK")
            for label, expr in (("USING", qual), ("WITH CHECK", with_check)):
                if expr and "nullif" not in expr.lower():
                    failures.append(f"{name}: {label} is not nullif-guarded")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nall assertions passed")
    return 0


def cmd_grant(conn: psycopg.Connection, app_role: str) -> int:
    """Re-run 003_grants.sql against a now-known application role.

    Migrations are applied once and never re-run, but the App's service principal
    usually does not exist yet when the schema is first created. This replays the
    same file — it is idempotent — with hazel.app_role bound, so the grant logic
    lives in exactly one place.
    """
    path = MIGRATIONS_DIR / "003_grants.sql"
    if not path.is_file():
        print(f"missing {path}", file=sys.stderr)
        return 1

    notices: list[str] = []
    conn.add_notice_handler(lambda diag: notices.append(diag.message_primary or ""))
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('hazel.app_role', %s, true)", (app_role,))
                cur.execute(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"grant failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    for message in notices:
        print(f"  {message}")
    print(f"grants applied for role {app_role}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="list applied/pending")
    parser.add_argument("--verify", action="store_true", help="run §8 step 2 assertions")
    parser.add_argument(
        "--grant",
        metavar="ROLE",
        help="grant schema access to the App's service principal client id",
    )
    args = parser.parse_args()

    # Ahead of connect(), and caught separately: an SDK without the Autoscaling
    # credential API is a dependency problem, not a connection problem, and the
    # handler below would file it under "could not connect".
    try:
        assert_sdk_capabilities()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"databricks-sdk {sdk_version()}")

    try:
        conn = connect()
    except Exception as exc:
        print(f"could not connect: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    with conn:
        with conn.cursor() as cur:
            cur.execute(TRACKING_DDL)
        conn.commit()

        if args.status:
            return cmd_status(conn)
        if args.verify:
            return cmd_verify(conn)
        if args.grant:
            return cmd_grant(conn, args.grant)
        rc = cmd_apply(conn)
        return cmd_verify(conn) if rc == 0 else rc


if __name__ == "__main__":
    raise SystemExit(main())
