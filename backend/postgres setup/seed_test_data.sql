-- Seed as the application role, using the anonymous-intake context.
BEGIN;
SET ROLE hop_app;
SELECT set_config('hop.role','SYSTEM',true);

INSERT INTO hazel.institution (id, legal_name, fdic_certificate, institution_type, registration_contact_email)
VALUES ('11111111-1111-1111-1111-111111111111','Alpha Bank NA','FDIC-1001','NATIONAL_BANK','ops@alpha.test'),
       ('22222222-2222-2222-2222-222222222222','Beta Savings','FDIC-2002','SAVINGS_INSTITUTION','ops@beta.test');

INSERT INTO hazel.app_user (id, institution_id, external_identity_id, email, first_name, last_name, role)
VALUES ('33333333-3333-3333-3333-333333333333','11111111-1111-1111-1111-111111111111','entra-a','a@alpha.test','Ann','Alpha','MEMBER_ADMIN'),
       ('44444444-4444-4444-4444-444444444444','22222222-2222-2222-2222-222222222222','entra-b','b@beta.test','Ben','Beta','MEMBER_ADMIN'),
       ('55555555-5555-5555-5555-555555555555',NULL,'entra-i','i@vantage.test','Ivy','Internal','INTERNAL_REVIEWER');

INSERT INTO hazel.onboarding_case (id, institution_id, case_number)
VALUES ('66666666-6666-6666-6666-666666666666','11111111-1111-1111-1111-111111111111','HOP-0001'),
       ('77777777-7777-7777-7777-777777777777','22222222-2222-2222-2222-222222222222','HOP-0002');
COMMIT;
