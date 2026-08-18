#!/usr/bin/env python3
"""Apply the Hazel schema to a Lakebase database in any workspace.

run_hazel.py already knows how to apply, seed and verify; what it cannot do is
authenticate. On Lakebase the Postgres password is a short-lived OAuth token, so
PGPASSWORD has to be minted rather than stored. This mints one for whichever
workspace DATABRICKS_HOST/DATABRICKS_TOKEN name, exports it, and hands over.

Usage — from the postgres setup directory, with the target workspace's variables
exported (see NEW_WORKSPACE.md):

    python apply_to_workspace.py check
    python apply_to_workspace.py all

The distinction that matters: DATABRICKS_HOST decides which workspace mints the
credential, and PGHOST decides which database it is presented to. They must
belong to the same workspace. Getting that pair wrong is the failure this script
exists to make visible, so it prints both before doing anything.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # so `import app.lakebase` resolves

REQUIRED = ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "PGHOST", "PGPORT",
            "PGDATABASE", "PGUSER", "PGSSLMODE", "ENDPOINT_NAME")


def main() -> int:
    missing = [v for v in REQUIRED if not os.environ.get(v)]
    if missing:
        print(f"missing environment variables: {missing}", file=sys.stderr)
        print("See NEW_WORKSPACE.md for where each value comes from.", file=sys.stderr)
        return 2

    # Printed before the mint, because a token minted against the wrong workspace
    # fails as an opaque authentication error against the right database.
    print(f"  workspace : {os.environ['DATABRICKS_HOST']}")
    print(f"  database  : {os.environ['PGUSER']}@{os.environ['PGHOST']}/{os.environ['PGDATABASE']}")
    print(f"  endpoint  : {os.environ['ENDPOINT_NAME']}")

    from app.lakebase import assert_sdk_capabilities, mint_password, resolve_settings, sdk_version

    # Ahead of the mint and reported separately: an SDK without the Autoscaling
    # credential API is a dependency problem, not a connection problem.
    assert_sdk_capabilities()
    print(f"  sdk       : databricks-sdk {sdk_version()}")

    try:
        token = mint_password(resolve_settings())
    except Exception as exc:
        print(f"\ncould not mint a Lakebase credential: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        print("If this names 'postgres' or 'endpoint', the target may be a Lakebase "
              "*instance* rather than an Autoscaling project — those use a different "
              "SDK call and a different ENDPOINT_NAME shape.", file=sys.stderr)
        return 1
    print("  credential: minted\n")

    env = {**os.environ, "PGPASSWORD": token}
    args = sys.argv[1:] or ["check"]
    return subprocess.call([sys.executable, str(HERE / "run_hazel.py"), *args], env=env)


if __name__ == "__main__":
    raise SystemExit(main())
