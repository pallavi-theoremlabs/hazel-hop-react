-- 2026-08-21_inquiry_contact_fields.sql
-- Applied once, by hand, against the deployed hazel schema.
--
-- WHERE INCREMENTAL DDL LIVES, AND WHY IT LIVES HERE
-- There is no migration runner. apps/api/migrate.py and apps/api/migrations/ were
-- deleted because they built a retired data model and wrote to production on every
-- invocation, including a command that only looks like it reads. And
-- postgres setup/hazel_schema.sql opens with DROP SCHEMA ... CASCADE, so it is a
-- clean-install script that cannot be applied incrementally.
--
-- So incremental DDL is a dated, reviewed file here, applied once, and mirrored
-- into hazel_schema.sql so a fresh install produces the same shape.
--
-- WHY THIS CHANGE
-- The public inquiry form collects a website, a contact phone number and a contact
-- job title. None of the three had a column anywhere in the schema, so
-- submit_interest dropped them: the applicant typed them and they were lost.
-- Confirmed against the live catalog on 2026-08-21 - no matching column on any of
-- the seven tables, and the only jsonb columns are trigger-written audit snapshots
-- and a document reference, none usable as a catch-all.
--
-- website is also a blocker rather than a nicety. app/routers/cases.py builds the
-- Coverbase profile with a hardcoded empty website, commented "the canonical schema
-- deliberately has no website column yet", and lists website in
-- required_express_interest - the fields a case needs before it can progress.
--
-- Deliberately NOT included: institution.headquarters. RAFA already returns it and
-- submit_interest holds it, so it would cost no frontend change, but it is parked
-- as a separate decision.
--
-- IF NOT EXISTS throughout, so a repeated or partial run is safe.

BEGIN;

ALTER TABLE hazel.institution ADD COLUMN IF NOT EXISTS website   text;
ALTER TABLE hazel."user"      ADD COLUMN IF NOT EXISTS phone     text;
ALTER TABLE hazel."user"      ADD COLUMN IF NOT EXISTS job_title text;

-- hop_app holds column-level UPDATE on institution, not table-level, so a new
-- column is not writable by the app until it is named here. The failure would
-- surface only on a REPEAT submission - the ON CONFLICT DO UPDATE path - never on
-- the first one, which is exactly the bug a happy-path test misses.
--
-- hazel."user" already carries table-level UPDATE, so phone and job_title need no
-- grant of their own.
GRANT UPDATE (website) ON hazel.institution TO hop_app;

COMMIT;
