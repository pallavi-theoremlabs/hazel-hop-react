#!/usr/bin/env python3
"""
Hazel HOP schema runner - applies and verifies the schema without psql.
 
Works on Windows / Git Bash / anywhere Python runs.
 
CONNECTING
----------
Preferred (no URL-encoding traps - use this if your username contains '@'):
 
    export PGHOST=instance-xxxx.database.cloud.databricks.com
    export PGPORT=5432
    export PGDATABASE=databricks_postgres
    export PGUSER='shardul.patki@theoremlabs.io'
    export PGPASSWORD='<your Lakebase OAuth token>'
    export PGSSLMODE=require
 
Or a single URL, where '@' inside the username MUST be written as %40:
 
    export HOP_DB_URL="postgresql://shardul.patki%40theoremlabs.io:TOKEN@host:5432/databricks_postgres?sslmode=require"
 
USAGE
-----
    python run_hazel.py check     # connection + who am I
    python run_hazel.py apply     # run hazel_schema.sql
    python run_hazel.py seed      # run seed_test_data.sql
    python run_hazel.py verify    # structure + behaviour tests
    python run_hazel.py all       # apply, seed, verify
    python run_hazel.py cleanup   # delete the test banks
 
Requires: pip install "psycopg[binary]"   (or psycopg2-binary)
"""
import os
import sys
import pathlib
 
# ---------------------------------------------------------------- driver
try:
    import psycopg
    DRIVER = 3
except ImportError:
    try:
        import psycopg2 as psycopg
        DRIVER = 2
    except ImportError:
        sys.exit('No Postgres driver found.\n'
                 '  pip install "psycopg[binary]"      (preferred)\n'
                 '  pip install psycopg2-binary        (also fine)')
 
HERE = pathlib.Path(__file__).parent
 
 
def connect():
    url = os.environ.get("HOP_DB_URL")
    if url:
        if url.count("@") > 1 and "%40" not in url:
            sys.exit("HOP_DB_URL has more than one '@'. Percent-encode the one in your\n"
                     "username as %40, or use the PGHOST/PGUSER/PGPASSWORD variables instead.")
        return psycopg.connect(url)
 
    missing = [v for v in ("PGHOST", "PGUSER", "PGDATABASE") if not os.environ.get(v)]
    if missing:
        sys.exit(f"Set HOP_DB_URL, or these variables: {', '.join(missing)}")
    return psycopg.connect(
        host=os.environ["PGHOST"],
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ.get("PGPASSWORD"),
        sslmode=os.environ.get("PGSSLMODE", "require"),
    )
 
 
def run_file(name):
    path = HERE / name
    if not path.exists():
        sys.exit(f"{name} not found in {HERE}")
    sql = path.read_text(encoding="utf-8")
    conn = connect()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        print(f"  OK   {name} applied")
    except Exception as exc:
        conn.rollback()
        print(f"  FAIL {name}\n       {exc}")
        sys.exit(1)
    finally:
        conn.close()
 
 
# ---------------------------------------------------------------- fixtures
A  = "11111111-1111-1111-1111-111111111111"
B  = "22222222-2222-2222-2222-222222222222"
UA = "33333333-3333-3333-3333-333333333333"
UB = "44444444-4444-4444-4444-444444444444"
UI = "55555555-5555-5555-5555-555555555555"
CA = "66666666-6666-6666-6666-666666666666"
CB = "77777777-7777-7777-7777-777777777777"
 
CTX_A = (f"SELECT set_config('hop.institution_id','{A}',true);"
         f"SELECT set_config('hop.user_id','{UA}',true);"
         f"SELECT set_config('hop.role','MEMBER_ADMIN',true);")
CTX_B = (f"SELECT set_config('hop.institution_id','{B}',true);"
         f"SELECT set_config('hop.user_id','{UB}',true);"
         f"SELECT set_config('hop.role','MEMBER_ADMIN',true);")
CTX_I = (f"SELECT set_config('hop.user_id','{UI}',true);"
         f"SELECT set_config('hop.role','INTERNAL_REVIEWER',true);")
CTX_N = ""
 
EXPECTED = [
    ("tables",     7,  "SELECT count(*) FROM information_schema.tables WHERE table_schema='hazel'"),
    ("columns",    80, "SELECT count(*) FROM information_schema.columns WHERE table_schema='hazel'"),
    ("FKs",        9,  "SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='hazel' AND contype='f'"),
    ("CHECKs",     26, "SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='hazel' AND contype='c'"),
    ("indexes",    26, "SELECT count(*) FROM pg_indexes WHERE schemaname='hazel'"),
    ("triggers",   13, "SELECT count(*) FROM pg_trigger t JOIN pg_class cl ON cl.oid=t.tgrelid JOIN pg_namespace n ON n.oid=cl.relnamespace WHERE n.nspname='hazel' AND NOT tgisinternal"),
    ("policies",   10, "SELECT count(*) FROM pg_policies WHERE schemaname='hazel'"),
    ("RLS forced", 7,  "SELECT count(*) FROM pg_class cl JOIN pg_namespace n ON n.oid=cl.relnamespace WHERE n.nspname='hazel' AND cl.relforcerowsecurity"),
]
 
D = ("institution_id,onboarding_case_id,uploaded_by,document_type_name,file_name,file_path")
 
TESTS = [
    ("TENANCY", [
        ("bank A sees exactly 1 case",              "ok", CTX_A + "SELECT count(*) FROM hazel.onboarding_case;"),
        ("bank B sees exactly 1 case",              "ok", CTX_B + "SELECT count(*) FROM hazel.onboarding_case;"),
        ("internal sees both cases",                "ok", CTX_I + "SELECT count(*) FROM hazel.onboarding_case;"),
        ("no session context sees nothing",         "ok", CTX_N + "SELECT count(*) FROM hazel.onboarding_case;"),
        ("A cannot read B's case by id",            "ok", CTX_A + f"SELECT count(*) FROM hazel.onboarding_case WHERE id='{CB}';"),
        ("A's update of B's case hits 0 rows",      "ok", CTX_A + f"UPDATE hazel.onboarding_case SET current_status='ON_HOLD' WHERE id='{CB}'; SELECT count(*) FROM hazel.onboarding_case WHERE id='{CB}' AND current_status='ON_HOLD';"),
        ("A cannot insert a case for B",            "no", CTX_A + f"INSERT INTO hazel.onboarding_case (institution_id,case_number) VALUES ('{B}','HOP-EVIL');"),
    ]),
    ("APPEND-ONLY HISTORY", [
        ("UPDATE audit_log denied",                 "no", CTX_I + "UPDATE hazel.audit_log SET action='INSERT';"),
        ("DELETE audit_log denied",                 "no", CTX_I + "DELETE FROM hazel.audit_log;"),
        ("UPDATE stage transitions denied",         "no", CTX_I + "UPDATE hazel.case_stage_transition SET to_stage='NDA';"),
        ("DELETE stage transitions denied",         "no", CTX_I + "DELETE FROM hazel.case_stage_transition;"),
    ]),
    ("PROTECTED COPY COLUMNS", [
        ("direct write institution.rssd_id denied", "no", CTX_I + f"UPDATE hazel.institution SET rssd_id='FAKE' WHERE id='{A}';"),
        ("direct write case.rafa_score denied",     "no", CTX_I + f"UPDATE hazel.onboarding_case SET rafa_score=99 WHERE id='{CA}';"),
        ("allowed column still writable",           "ok", CTX_I + f"UPDATE hazel.institution SET legal_name='Alpha Bank, N.A.' WHERE id='{A}'; SELECT legal_name FROM hazel.institution WHERE id='{A}';"),
        ("RAFA write propagates to both copies",    "ok", CTX_I + f"INSERT INTO hazel.rafa (institution_id,fdic_certificate,rssd_id,rafa_score,rafa_status) VALUES ('{A}','FDIC-1001','RSSD-777',88.50,'PASS') ON CONFLICT (institution_id) DO UPDATE SET rssd_id=EXCLUDED.rssd_id, rafa_score=EXCLUDED.rafa_score; SELECT (SELECT rssd_id FROM hazel.institution WHERE id='{A}')||' / '||(SELECT rafa_score::text FROM hazel.onboarding_case WHERE id='{CA}');"),
    ]),
    ("STAGE HISTORY (trigger-written)", [
        ("creation wrote an opening row",           "ok", CTX_A + f"SELECT count(*) FROM hazel.case_stage_transition WHERE onboarding_case_id='{CA}';"),
        ("stage change writes history",             "ok", CTX_A + f"UPDATE hazel.onboarding_case SET current_stage='NDA' WHERE id='{CA}'; SELECT count(*) FROM hazel.case_stage_transition WHERE onboarding_case_id='{CA}';"),
        ("no-op update writes no history",          "ok", CTX_A + f"UPDATE hazel.onboarding_case SET current_stage='NDA' WHERE id='{CA}'; SELECT count(*) FROM hazel.case_stage_transition WHERE onboarding_case_id='{CA}';"),
        ("history attributed to acting user",       "ok", CTX_A + f"UPDATE hazel.onboarding_case SET current_stage='DUE_DILIGENCE' WHERE id='{CA}'; SELECT actor_type||'/'||coalesce(changed_by::text,'null') FROM hazel.case_stage_transition WHERE onboarding_case_id='{CA}' ORDER BY occurred_at DESC LIMIT 1;"),
    ]),
    ("DOCUMENTS", [
        ("valid upload by own member",              "ok", CTX_A + f"INSERT INTO hazel.document ({D}) VALUES ('{A}','{CA}','{UA}','NDA','nda.pdf','/Volumes/hazel/onboarding/uploads/{A}/{CA}/d1.pdf'); SELECT 'ok';"),
        ("internal reviewer may upload for A",      "ok", CTX_I + f"INSERT INTO hazel.document ({D}) VALUES ('{A}','{CA}','{UI}','CBDDQ','c.pdf','/v/x/d2.pdf'); SELECT 'ok';"),
        ("uploader from another bank rejected",     "no", CTX_I + f"INSERT INTO hazel.document ({D}) VALUES ('{A}','{CA}','{UB}','NDA','x.pdf','/v/x/d3.pdf');"),
        ("institution/case mismatch rejected",      "no", CTX_I + f"INSERT INTO hazel.document ({D}) VALUES ('{B}','{CA}','{UI}','NDA','x.pdf','/v/x/d4.pdf');"),
        ("unknown document type rejected",          "no", CTX_A + f"INSERT INTO hazel.document ({D}) VALUES ('{A}','{CA}','{UA}','PASSPORT','x.pdf','/v/x/d5.pdf');"),
        ("bank B cannot see A's documents",         "ok", CTX_B + "SELECT count(*) FROM hazel.document;"),
    ]),
    ("BUSINESS RULES", [
        ("second active case for A rejected",       "no", CTX_I + f"INSERT INTO hazel.onboarding_case (institution_id,case_number) VALUES ('{A}','HOP-0003');"),
        ("closing the case frees the slot",         "ok", CTX_I + f"UPDATE hazel.onboarding_case SET current_status='WITHDRAWN' WHERE id='{CA}'; INSERT INTO hazel.onboarding_case (institution_id,case_number) VALUES ('{A}','HOP-0003') ON CONFLICT (case_number) DO NOTHING; SELECT 'ok';"),
        ("internal user with institution rejected", "no", CTX_I + f"INSERT INTO hazel.app_user (institution_id,external_identity_id,email,role) VALUES ('{A}','e-x','x@v.test','INTERNAL_RISK');"),
        ("member user without institution rejected","no", CTX_I + "INSERT INTO hazel.app_user (institution_id,external_identity_id,email,role) VALUES (NULL,'e-y','y@v.test','MEMBER_VIEWER');"),
        ("malformed sha256 rejected",               "no", CTX_A + f"INSERT INTO hazel.document ({D},sha256) VALUES ('{A}','{CA}','{UA}','NDA','x.pdf','/v/x/d6.pdf','nothex');"),
        ("invalid stage value rejected",            "no", CTX_I + f"UPDATE hazel.onboarding_case SET current_stage='TYPO_STAGE' WHERE id='{CB}';"),
    ]),
    # Each test runs in its own rolled-back transaction, so an audit assertion
    # must make the change it is checking for inside the same transaction.
    ("AUDIT", [
        ("legal_name change captured",              "ok", CTX_I + f"UPDATE hazel.institution SET legal_name='Renamed Bank' WHERE id='{A}'; SELECT action||' '||changed_fields::text FROM hazel.audit_log WHERE entity_type='institution' AND changed_fields @> ARRAY['legal_name'] ORDER BY id DESC LIMIT 1;"),
        ("before/after both recorded",              "ok", CTX_I + f"UPDATE hazel.institution SET legal_name='Renamed Bank' WHERE id='{A}'; SELECT (before_data->>'legal_name')||' -> '||(after_data->>'legal_name') FROM hazel.audit_log WHERE entity_type='institution' AND changed_fields @> ARRAY['legal_name'] ORDER BY id DESC LIMIT 1;"),
        ("all five core tables audited",            "ok", CTX_I + f"""
             UPDATE hazel.institution SET legal_name='Audit Probe' WHERE id='{A}';
             INSERT INTO hazel.rafa (institution_id,rssd_id,rafa_score,rafa_status)
               VALUES ('{A}','RSSD-1','10.00','PASS')
               ON CONFLICT (institution_id) DO UPDATE SET rafa_score=EXCLUDED.rafa_score;
             UPDATE hazel.onboarding_case SET current_stage='NDA' WHERE id='{CA}';
             INSERT INTO hazel.document ({D}) VALUES ('{A}','{CA}','{UI}','NDA','a.pdf','/v/a.pdf');
             INSERT INTO hazel.app_user (institution_id,external_identity_id,email,role)
               VALUES ('{A}','probe-1','probe@alpha.test','MEMBER_VIEWER');
             SELECT string_agg(DISTINCT entity_type,',' ORDER BY entity_type) FROM hazel.audit_log;"""),
        ("A sees no audit rows for B",              "ok", CTX_A + f"SELECT count(*) FROM hazel.audit_log WHERE institution_id='{B}';"),
    ]),
]
 
 
def _last_value(cur):
    """Walk to the final result set. psycopg3 keeps one per statement and only
    exposes the first until nextset(); psycopg2 keeps only the last."""
    val = ""
    while True:
        try:
            if cur.description:
                row = cur.fetchone()
                # an empty result set must NOT silently inherit the previous
                # statement's value - that hides broken assertions
                val = row[0] if row is not None else "(no rows)"
        except Exception:
            pass
        nextset = getattr(cur, "nextset", None)
        if nextset is None or not nextset():
            break
    return "" if val is None else val
 
 
def one(conn, sql):
    """Run inside a rolled-back transaction as hop_app. Returns (ok, value_or_error)."""
    try:
        with conn.cursor() as cur:
            cur.execute("SET ROLE hop_app;" + sql)
            val = _last_value(cur)
        conn.rollback()
        return True, val
    except Exception as exc:
        conn.rollback()
        return False, str(exc).strip().split("\n")[0]
 
 
def cmd_check():
    conn = connect()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT current_user, version()")
        user, ver = cur.fetchone()
        cur.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user")
        bypass = cur.fetchone()[0]
    print(f"  connected as : {user}")
    print(f"  server       : {ver.split(',')[0]}")
    print(f"  bypassrls    : {bypass}  {'(RLS will NOT apply to you - test via SET ROLE)' if bypass else ''}")
    conn.close()
 
 
def cmd_verify():
    conn = connect()
    conn.autocommit = False
    npass = nfail = 0
 
    print("\n=== STRUCTURE ===")
    for label, want, sql in EXPECTED:
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                got = cur.fetchone()[0]
            conn.rollback()
        except Exception as exc:
            conn.rollback()
            print(f"  FAIL  {label:<12} {exc}")
            nfail += 1
            continue
        if got == want:
            print(f"  PASS  {label:<12} {got}")
            npass += 1
        else:
            print(f"  FAIL  {label:<12} expected {want}, got {got}")
            nfail += 1
 
    print("\n=== HARNESS SELF-CHECK ===")
    ok, val = one(conn, "SELECT current_user||' bypassrls='||"
                        "(SELECT rolbypassrls::text FROM pg_roles WHERE rolname=current_user);")
    if ok and "bypassrls=false" in str(val):
        print(f"  PASS  running as {val} - RLS is genuinely in effect")
        npass += 1
    else:
        print(f"  FAIL  {val}")
        print("        Every tenancy result below is meaningless. "
              "Run: GRANT hop_app TO \"<your-login>\";")
        nfail += 1
 
    for section, cases in TESTS:
        print(f"\n=== {section} ===")
        for desc, want, sql in cases:
            ok, val = one(conn, sql)
            if want == "ok":
                if ok:
                    print(f"  PASS  {desc}  -> {val}")
                    npass += 1
                else:
                    print(f"  FAIL  {desc}  -> {val}")
                    nfail += 1
            else:
                if not ok:
                    print(f"  PASS  {desc}  (rejected)")
                    npass += 1
                else:
                    print(f"  FAIL  {desc}  SHOULD HAVE BEEN REJECTED -> {val}")
                    nfail += 1
 
    conn.close()
    print("\n" + "=" * 53)
    print(f"  {npass} passed, {nfail} failed")
    print("=" * 53)
    return 1 if nfail else 0
 
 
def cmd_cleanup():
    conn = connect()
    conn.autocommit = False
    with conn.cursor() as cur:
        cur.execute(f"""
            SET ROLE hop_app;
            SELECT set_config('hop.role','INTERNAL_ADMIN',true);
            DELETE FROM hazel.document           WHERE institution_id IN ('{A}','{B}');
            DELETE FROM hazel.case_stage_transition WHERE institution_id IN ('{A}','{B}');
        """)
    conn.rollback()
    print("  Test rows are protected by append-only rules on history tables.")
    print("  To remove the test banks entirely, re-run: python run_hazel.py apply")
    conn.close()
 
 
def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "check":
        cmd_check()
    elif cmd == "apply":
        run_file("hazel_schema.sql")
    elif cmd == "seed":
        run_file("seed_test_data.sql")
    elif cmd == "verify":
        sys.exit(cmd_verify())
    elif cmd == "cleanup":
        cmd_cleanup()
    elif cmd == "all":
        cmd_check()
        print("\n=== APPLYING SCHEMA ===")
        run_file("hazel_schema.sql")
        print("\n=== SEEDING TEST DATA ===")
        run_file("seed_test_data.sql")
        sys.exit(cmd_verify())
    else:
        sys.exit(__doc__)
 
 
if __name__ == "__main__":
    main()