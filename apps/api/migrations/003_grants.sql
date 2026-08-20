-- 003_grants.sql — privileges for the application role.
--
-- The original assumption here was "the connecting role owns the database, so no
-- grants are needed." That is true for whoever runs the migrations and false for
-- the deployed App, and the difference is easy to miss:
--
--   * Migrations are run by a human identity (or CI), and every object created
--     is owned by that identity.
--   * The App connects as PGUSER, which is its service principal's
--     DATABRICKS_CLIENT_ID — a different role, owning nothing.
--
-- Verified against the real endpoint: after running migrations as
-- shardul.patki@theoremlabs.io, `hazel` is owned by that user. An App connecting
-- as its SP would get "permission denied for schema hazel" on its first query.
--
-- So the grants are real, and the role to grant to is supplied at run time:
--
--     SET hazel.app_role = '<service-principal-client-id>';
--
-- When the App does not exist yet, leave it unset — this file then issues no
-- grants and says so, rather than guessing a role name. Once the SP is known,
-- re-run the same statements without a new migration:
--
--     python backend/migrate.py --grant <service-principal-client-id>
--
-- Note that grants do not weaken tenancy. Every table is FORCE ROW LEVEL
-- SECURITY (002), so the App role is still filtered by the org_isolation policy;
-- these grants only decide whether it may reach the tables at all.
--
-- `databricks_create_role(...)` deliberately does not appear here — that belongs
-- to the Lakebase *instances* model, and this deployment is Autoscaling.
--
-- search_path is NOT set here. `ALTER ROLE ... SET search_path = hazel` requires
-- privileges Lakebase does not grant, so the schema is selected per physical
-- connection instead, in the engine:
--
--     create_engine(..., connect_args={"options": "-c search_path=hazel"})
--
-- That applies at connect time, costs nothing per request, and survives pool
-- churn. It deliberately does not live in the request path — it is a constant,
-- and it belongs with the connection rather than the transaction.

DO $$
DECLARE
    app_role     text := nullif(current_setting('hazel.app_role', true), '');
    schema_owner text;
BEGIN
    SELECT pg_catalog.pg_get_userbyid(nspowner)
      INTO schema_owner
      FROM pg_catalog.pg_namespace
     WHERE nspname = 'hazel';

    IF schema_owner IS DISTINCT FROM current_user THEN
        RAISE EXCEPTION
            'schema hazel is owned by % but this is running as %. Grants below '
            'assume the migration runner owns the schema; resolve ownership '
            'rather than widening privileges.',
            schema_owner, current_user;
    END IF;

    IF app_role IS NULL THEN
        RAISE NOTICE
            'hazel.app_role is not set, so no grants were issued. The deployed '
            'App connects as its service principal client id, which is NOT %. '
            'Run: python backend/migrate.py --grant <client-id>  before deploying.',
            current_user;
        RETURN;
    END IF;

    IF app_role = current_user THEN
        RAISE NOTICE 'app role % already owns schema hazel; no grants required', app_role;
        RETURN;
    END IF;

    -- CREATE as well as USAGE: the app's runtime queries need only USAGE, but
    -- whoever runs migrations needs CREATE, and on Lakebase that may be the same
    -- service principal. Verified end state has has_schema_privilege true for both.
    EXECUTE format('GRANT USAGE, CREATE ON SCHEMA hazel TO %I', app_role);
    EXECUTE format(
        'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA hazel TO %I',
        app_role);
    EXECUTE format(
        'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA hazel TO %I', app_role);

    -- Tables added by later migrations would otherwise be unreachable until
    -- someone remembered to re-grant.
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES IN SCHEMA hazel '
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', app_role);
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES IN SCHEMA hazel '
        'GRANT USAGE, SELECT ON SEQUENCES TO %I', app_role);

    RAISE NOTICE 'granted schema hazel access to app role %', app_role;
END
$$;
