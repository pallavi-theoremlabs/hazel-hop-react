-- 00_role.sql — must run BEFORE 01_schema.sql.
--
-- Roles are cluster-wide objects, not schema members, so `pg_dump --schema=hazel`
-- does not carry them. The dump contains 66 GRANT statements naming hop_app, and
-- every one of them fails with "role hop_app does not exist" without this.
--
-- NOLOGIN NOBYPASSRLS, copied from hazel_schema.sql and load-bearing in both
-- halves. NOLOGIN because nothing authenticates as this role directly — the
-- application connects as its Databricks identity and does SET LOCAL ROLE.
-- NOBYPASSRLS because Databricks identities carry rolbypassrls, so without a role
-- that explicitly cannot bypass, every p_tenant policy silently does nothing.

DO $do$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hop_app') THEN
    CREATE ROLE hop_app NOLOGIN NOBYPASSRLS;
  END IF;
END
$do$;
