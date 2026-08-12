-- 002_rls.sql — row-level tenant isolation.
--
-- Applied to all seven tenant-scoped tables. Every one gets both ENABLE and
-- FORCE: ENABLE alone exempts the table owner, and the application connects as
-- PGUSER (the app service principal's DATABRICKS_CLIENT_ID), which owns these
-- tables. Without FORCE the policies below would never be evaluated in
-- production.
--
-- The predicate:
--
--     org_id = nullif(current_setting('app.org_id', true), '')::uuid
--
-- The `true` second argument to current_setting makes it return NULL instead of
-- raising when the GUC has never been set. `org_id = NULL` evaluates to NULL,
-- which the policy treats as "not visible" — so a forgotten set_config yields
-- zero rows rather than every row. That is the correct fail-closed direction.
--
-- The nullif() wrapper handles the other case, which the bare expression gets
-- wrong: a GUC that was explicitly set to the empty string. current_setting then
-- returns '' rather than NULL, and ''::uuid raises
--
--     invalid input syntax for type uuid: ""   (SQLSTATE 22P02)
--
-- turning a missing tenant context into a 500 on every query instead of an empty
-- result. nullif collapses '' back to NULL and restores the fail-closed
-- behaviour. It is needed on WITH CHECK as well as USING, or writes raise while
-- reads quietly return nothing.
--
-- WITH CHECK is present on every policy alongside USING. USING alone filters
-- what a tenant can see but still permits writing rows belonging to another org.

SET search_path = hazel, public;


ALTER TABLE hazel.onboarding_cases             ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel.onboarding_cases             FORCE  ROW LEVEL SECURITY;
ALTER TABLE hazel.institution_profiles         ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel.institution_profiles         FORCE  ROW LEVEL SECURITY;
ALTER TABLE hazel.express_interest_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel.express_interest_submissions FORCE  ROW LEVEL SECURITY;
ALTER TABLE hazel.documents                    ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel.documents                    FORCE  ROW LEVEL SECURITY;
ALTER TABLE hazel.due_diligence                ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel.due_diligence                FORCE  ROW LEVEL SECURITY;
ALTER TABLE hazel.review_clarifications        ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel.review_clarifications        FORCE  ROW LEVEL SECURITY;
ALTER TABLE hazel.case_decisions               ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel.case_decisions               FORCE  ROW LEVEL SECURITY;


CREATE POLICY org_isolation ON hazel.onboarding_cases
    USING      (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
    WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);

CREATE POLICY org_isolation ON hazel.institution_profiles
    USING      (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
    WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);

CREATE POLICY org_isolation ON hazel.express_interest_submissions
    USING      (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
    WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);

CREATE POLICY org_isolation ON hazel.documents
    USING      (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
    WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);

CREATE POLICY org_isolation ON hazel.due_diligence
    USING      (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
    WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);

CREATE POLICY org_isolation ON hazel.review_clarifications
    USING      (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
    WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);

CREATE POLICY org_isolation ON hazel.case_decisions
    USING      (org_id = nullif(current_setting('app.org_id', true), '')::uuid)
    WITH CHECK (org_id = nullif(current_setting('app.org_id', true), '')::uuid);


-- hazel.organizations is deliberately NOT under RLS. It is the tenant registry
-- itself, it is read by the migration runner and by startup assertions before any
-- tenant context exists, and putting the org table behind a policy keyed on the
-- org id creates a chicken-and-egg problem. It holds no tenant data.
