# Copying the hazel schema to another Databricks workspace

Produces a byte-faithful copy of the **live** Lakebase schema — not a re-run of
`hazel_schema.sql`. The two differ: the live database predates the `user` ->
`app_user` rename, so running the file would create a schema that is correct
by the file's lights and different from what the application has been tested
against. `pg_dump` copies what is actually there.

Everything in `dump/` was generated from the source database and is committed as
evidence of what was copied.

| File | What it carries |
|---|---|
| `00_role.sql` | `hop_app` role. Roles are cluster-wide, so a schema dump omits them, and all 66 GRANTs fail without it. |
| `01_schema.sql` | 7 tables, 80 columns, 46 constraints, 26 indexes, 13 triggers, 9 functions, 10 policies, RLS enable+force, column-level grants, comments. |
| `02_data.sql` | 16 rows: 2 institutions, 3 users, 2 cases, 2 stage transitions, 7 audit entries. |
| `source_fingerprint.json` | Canonical structure of the source, for the parity diff in step 5. |

`hazel.schema_migrations` is deliberately excluded. It was created by an
accidental `migrate.py --status` run against the retired `backend/migrations/`
model and is not part of this schema.

---

## 0. Test egress FIRST

The entire reason for the trial workspace. Do this before copying anything —
if it fails, the copy buys you nothing.

Deploy the app as-is to the new workspace, then:

    curl -s -H "Authorization: Bearer $OAUTH" -H "X-Hazel-Proxy-Key: $KEY" \
      https://<new-app>.aws.databricksapps.com/api/public/banks/fdic/628

Returning JPMorgan Chase means egress is open on paid tiers. A 20-second hang
followed by 503 means it is not, and no schema work changes that.

## 1. Create a Lakebase database in the new workspace

Catalog -> Database instances -> Create. Record all six values; they are the
only source and nothing here reconstructs them:

    PGHOST PGPORT PGDATABASE PGUSER PGSSLMODE ENDPOINT_NAME

`ENDPOINT_NAME` is the name form, not the UID form:
`projects/<project>/branches/<branch>/endpoints/<endpoint>`. Copy it whole from
the UI.

If the new workspace offers a Lakebase **instance** rather than an Autoscaling
**project**, stop: `app/lakebase.py` targets the Autoscaling credential API
(`w.postgres.generate_database_credential(endpoint=...)`) and an instance needs
the other one. There is deliberately no fallback between them.

## 2. Point the environment at the new workspace

    unset DATABRICKS_TOKEN DATABRICKS_HOST DATABRICKS_CLIENT_ID DATABRICKS_CLIENT_SECRET
    export DATABRICKS_HOST=https://<new-workspace>.cloud.databricks.com
    export DATABRICKS_TOKEN=<new PAT>
    export PGHOST=... PGPORT=5432 PGDATABASE=... PGUSER=... PGSSLMODE=require
    export ENDPOINT_NAME=projects/.../branches/.../endpoints/...

The `unset` is not optional. A stale `DATABRICKS_HOST` from another account has
broken this twice: the credential is minted by whichever workspace
`DATABRICKS_HOST` names, and presented to whichever database `PGHOST` names.
Mismatch them and the failure is an opaque authentication error.

## 3. Apply

    export PATH="$PATH:/c/Program Files/PostgreSQL/17/bin"
    export PGPASSWORD="$(python -c "
    import sys; sys.path.insert(0,'..')
    from app.lakebase import resolve_settings, mint_password
    print(mint_password(resolve_settings()))")"

    psql -h "$PGHOST" -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -f dump/00_role.sql
    psql -h "$PGHOST" -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -f dump/01_schema.sql
    psql -h "$PGHOST" -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -f dump/02_data.sql

`ON_ERROR_STOP=1` matters: without it psql reports success having skipped every
statement after the first failure.

## 4. Grant the app's service principal

Two separate grants, in two separate systems. Both are required.

Lakebase — membership of the role the RLS policies are written against:

    GRANT hop_app TO "<new-app-service-principal-client-id>";

Unity Catalog — only if you also create a Volume for document storage:

    GRANT USE CATALOG ON CATALOG hazel TO `<sp>`;
    GRANT USE SCHEMA ON SCHEMA hazel.onboarding TO `<sp>`;
    GRANT READ VOLUME, WRITE VOLUME ON VOLUME hazel.onboarding.uploads TO `<sp>`;

## 5. Prove the copy is faithful

    python fingerprint.py > dump/target_fingerprint.json
    diff dump/source_fingerprint.json dump/target_fingerprint.json && echo IDENTICAL

Expected: no output. The fingerprint reads catalogs directly rather than trusting
the dump, and covers columns with exact types/nullability/defaults, every
constraint and index definition, triggers, RLS enable+force flags, policy USING
and WITH CHECK expressions, column-level grants and function bodies.

Two diffs are expected and benign:

* **grants** rows naming the source owner (`shardul.patki@theoremlabs.io`) rather
  than the new workspace's identity. Ownership is per-workspace. What must match
  is every `hop_app` row — especially the column-level UPDATE grants on
  `institution` and `onboarding_case`, which are what stop the application
  writing the `rssd_id` and `rafa_score` copies that `fn_propagate_rafa` owns.
* nothing else. A diff anywhere in `columns`, `constraints`, `indexes`,
  `policies`, `rls`, `triggers` or `functions` is a real difference.
