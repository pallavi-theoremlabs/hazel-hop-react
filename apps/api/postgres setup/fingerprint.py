#!/usr/bin/env python3
"""Canonical structural fingerprint of the hazel schema, for proving two
databases match.

"Apply the dump and it will be identical" is a claim, not evidence. pg_dump is
faithful about what it emits, but it does not carry roles, it can be run with the
wrong flags, and a target database may have pre-existing objects the dump does not
overwrite. This reads the catalogs directly and emits sorted JSON, so
`diff <(fingerprint source) <(fingerprint target)` is the evidence.

Everything the copy is supposed to preserve is included: columns with their exact
types, nullability and defaults; every constraint definition; every index
definition; triggers; RLS enabled/forced flags; policy USING and WITH CHECK
expressions; column-level grants; and function bodies.

Column-level grants matter more than they look: hazel_schema.sql grants UPDATE
column by column on institution and onboarding_case to keep the maintained copies
of rssd_id and rafa_score writable only by the propagation trigger. A table-level
GRANT would silently widen that, and a diff of `grants` is what catches it.

Usage:
    python fingerprint.py > source.json     # with PG* env vars pointing at source
    python fingerprint.py > target.json     # ... and at the target
    diff source.json target.json
"""
from __future__ import annotations

import json
import os
import sys

import psycopg

Q = {
    "columns": """
        SELECT table_name, column_name, data_type, udt_name, is_nullable,
               column_default, character_maximum_length, numeric_precision, numeric_scale
          FROM information_schema.columns
         WHERE table_schema='hazel' AND table_name <> 'schema_migrations'
         ORDER BY table_name, column_name""",
    "constraints": """
        SELECT cl.relname, c.conname, pg_get_constraintdef(c.oid)
          FROM pg_constraint c
          JOIN pg_class cl ON cl.oid=c.conrelid
          JOIN pg_namespace n ON n.oid=cl.relnamespace
         WHERE n.nspname='hazel' AND cl.relname <> 'schema_migrations'
         ORDER BY cl.relname, c.conname""",
    "indexes": """
        SELECT tablename, indexname, indexdef FROM pg_indexes
         WHERE schemaname='hazel' AND tablename <> 'schema_migrations'
         ORDER BY tablename, indexname""",
    "triggers": """
        SELECT cl.relname, t.tgname, pg_get_triggerdef(t.oid)
          FROM pg_trigger t
          JOIN pg_class cl ON cl.oid=t.tgrelid
          JOIN pg_namespace n ON n.oid=cl.relnamespace
         WHERE n.nspname='hazel' AND NOT t.tgisinternal
         ORDER BY cl.relname, t.tgname""",
    "rls": """
        SELECT cl.relname, cl.relrowsecurity, cl.relforcerowsecurity
          FROM pg_class cl JOIN pg_namespace n ON n.oid=cl.relnamespace
         WHERE n.nspname='hazel' AND cl.relkind='r' AND cl.relname <> 'schema_migrations'
         ORDER BY cl.relname""",
    "policies": """
        SELECT tablename, policyname, permissive, cmd, qual, with_check
          FROM pg_policies WHERE schemaname='hazel'
         ORDER BY tablename, policyname""",
    "grants": """
        SELECT table_name, grantee, privilege_type, 'TABLE'
          FROM information_schema.role_table_grants
         WHERE table_schema='hazel' AND table_name <> 'schema_migrations'
        UNION ALL
        SELECT table_name, grantee, privilege_type, 'COLUMN:'||column_name
          FROM information_schema.column_privileges
         WHERE table_schema='hazel' AND table_name <> 'schema_migrations'
         ORDER BY 1,2,3,4""",
    "functions": """
        SELECT p.proname, pg_get_functiondef(p.oid)
          FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
         WHERE n.nspname='hazel' ORDER BY p.proname""",
}


def main() -> int:
    missing = [v for v in ("PGHOST", "PGUSER", "PGDATABASE", "PGPASSWORD") if not os.environ.get(v)]
    if missing:
        print(f"missing env: {missing}", file=sys.stderr)
        return 2
    conn = psycopg.connect(
        host=os.environ["PGHOST"], port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ["PGDATABASE"], user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"], sslmode=os.environ.get("PGSSLMODE", "require"),
    )
    out = {}
    with conn.cursor() as cur:
        for name, sql in Q.items():
            cur.execute(sql)
            # Sorted and stringified so the diff is stable across servers that
            # order catalog scans differently.
            out[name] = sorted([str(c) for c in row] for row in cur.fetchall())
    conn.close()
    json.dump(out, sys.stdout, indent=1, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
