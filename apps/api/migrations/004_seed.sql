-- 004_seed.sql — the demo org and the HAZEL-TEST-001 fixture.
--
-- Ported from the INSERT OR IGNORE block that used to run on every boot at
-- db.py:166-200. It runs once here instead, and `ON CONFLICT DO NOTHING` keeps it
-- re-runnable.
--
-- The tenant context has to be established before touching any RLS-protected
-- table: these tables are FORCE ROW LEVEL SECURITY as of 002, the migration
-- runner connects as their owner, and the WITH CHECK on every policy would reject
-- these inserts with no app.org_id set. set_config(..., true) is transaction-local
-- and the runner wraps each file in one transaction, so it does not leak.

SET search_path = hazel, public;

-- hazel.organizations is not under RLS, so this one goes first and unguarded.
INSERT INTO hazel.organizations (id, slug, name)
VALUES ('00000000-0000-0000-0000-000000000001', 'demo', 'Hazel Demo Organization')
ON CONFLICT (id) DO NOTHING;

SELECT set_config('app.org_id', '00000000-0000-0000-0000-000000000001', true);

-- org_id is omitted from every INSERT below on purpose. Its column DEFAULT is the
-- same current_setting() expression the RLS policy checks, so the value written and
-- the value verified cannot diverge.

INSERT INTO hazel.onboarding_cases
    (id, institution_id, current_stage, review_status, created_at, updated_at)
VALUES
    ('HAZEL-TEST-001', 'NORTHSTAR-001', 'NDA_PENDING', 'Not started', now(), now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO hazel.institution_profiles
    (case_id, legal_name, fdic_certificate_number, rssd_id, institution_type,
     website, headquarters, admission_type,
     international_correspondent_relationships, has_dba,
     has_fintech_or_baas_programs, primary_contact_name,
     primary_contact_title, primary_contact_email, updated_at)
VALUES
    ('HAZEL-TEST-001', 'Northstar Community Bank, N.A.', '12001', '',
     'National bank', 'https://northstar.example', 'Charlotte, North Carolina',
     '', '', '', '', 'Jamie Chen', 'Chief Operating Officer',
     'jamie.chen@northstar.example', now())
ON CONFLICT (case_id) DO NOTHING;

INSERT INTO hazel.due_diligence (case_id, data_json, updated_at)
VALUES
    ('HAZEL-TEST-001',
     '{"institutionWebsite": "https://northstar.example", "headquarters": "Charlotte, North Carolina"}'::jsonb,
     now())
ON CONFLICT (case_id) DO NOTHING;

-- Mirrors the SELECT-from-institution_profiles form the SQLite seed used
-- (db.py:190-200), so the two stay consistent if the profile above is edited.
INSERT INTO hazel.express_interest_submissions
    (case_id, legal_name, fdic_certificate_number, rssd_id, institution_type,
     website, headquarters, contact_name, contact_title, contact_email,
     data_json, updated_at)
SELECT case_id, legal_name, fdic_certificate_number, rssd_id,
       institution_type, website, headquarters, primary_contact_name,
       primary_contact_title, primary_contact_email, '{}'::jsonb, updated_at
FROM hazel.institution_profiles
WHERE case_id = 'HAZEL-TEST-001'
ON CONFLICT (case_id) DO NOTHING;
