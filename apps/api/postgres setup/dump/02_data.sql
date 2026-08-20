--
-- PostgreSQL database dump
--

\restrict C5MAMSCfXGCql0mKi7jBcGeZnLUI3rSqfAIsRp16FVZwhCgsmL8VDAhiXJgKtMq

-- Dumped from database version 17.10 (29ad1b7)
-- Dumped by pg_dump version 17.11

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: institution; Type: TABLE DATA; Schema: hazel; Owner: -
--

INSERT INTO hazel.institution (id, legal_name, fdic_certificate, rssd_id, institution_type, status, registration_contact_email, created_at, updated_at) VALUES ('11111111-1111-1111-1111-111111111111', 'Alpha Bank NA', 'FDIC-1001', NULL, 'NATIONAL_BANK', 'PROSPECT', 'ops@alpha.test', '2026-08-14 23:02:12.298016+00', '2026-08-14 23:02:12.298016+00');
INSERT INTO hazel.institution (id, legal_name, fdic_certificate, rssd_id, institution_type, status, registration_contact_email, created_at, updated_at) VALUES ('22222222-2222-2222-2222-222222222222', 'Beta Savings', 'FDIC-2002', NULL, 'SAVINGS_INSTITUTION', 'PROSPECT', 'ops@beta.test', '2026-08-14 23:02:12.298016+00', '2026-08-14 23:02:12.298016+00');


--
-- Data for Name: user; Type: TABLE DATA; Schema: hazel; Owner: -
--

INSERT INTO hazel."user" (id, institution_id, external_identity_id, email, first_name, last_name, role, created_at, updated_at) VALUES ('33333333-3333-3333-3333-333333333333', '11111111-1111-1111-1111-111111111111', 'entra-a', 'a@alpha.test', 'Ann', 'Alpha', 'MEMBER_ADMIN', '2026-08-14 23:02:12.298016+00', '2026-08-14 23:02:12.298016+00');
INSERT INTO hazel."user" (id, institution_id, external_identity_id, email, first_name, last_name, role, created_at, updated_at) VALUES ('44444444-4444-4444-4444-444444444444', '22222222-2222-2222-2222-222222222222', 'entra-b', 'b@beta.test', 'Ben', 'Beta', 'MEMBER_ADMIN', '2026-08-14 23:02:12.298016+00', '2026-08-14 23:02:12.298016+00');
INSERT INTO hazel."user" (id, institution_id, external_identity_id, email, first_name, last_name, role, created_at, updated_at) VALUES ('55555555-5555-5555-5555-555555555555', NULL, 'entra-i', 'i@vantage.test', 'Ivy', 'Internal', 'INTERNAL_REVIEWER', '2026-08-14 23:02:12.298016+00', '2026-08-14 23:02:12.298016+00');


--
-- Data for Name: audit_log; Type: TABLE DATA; Schema: hazel; Owner: -
--

INSERT INTO hazel.audit_log (id, institution_id, entity_type, entity_id, action, changed_by, actor_type, changed_fields, before_data, after_data, occurred_at) OVERRIDING SYSTEM VALUE VALUES (1, '11111111-1111-1111-1111-111111111111', 'institution', '11111111-1111-1111-1111-111111111111', 'INSERT', NULL, 'SYSTEM', NULL, NULL, '{"id": "11111111-1111-1111-1111-111111111111", "status": "PROSPECT", "rssd_id": null, "created_at": "2026-08-14T23:02:12.298016+00:00", "legal_name": "Alpha Bank NA", "updated_at": "2026-08-14T23:02:12.298016+00:00", "fdic_certificate": "FDIC-1001", "institution_type": "NATIONAL_BANK", "registration_contact_email": "ops@alpha.test"}', '2026-08-14 23:02:12.298016+00');
INSERT INTO hazel.audit_log (id, institution_id, entity_type, entity_id, action, changed_by, actor_type, changed_fields, before_data, after_data, occurred_at) OVERRIDING SYSTEM VALUE VALUES (2, '22222222-2222-2222-2222-222222222222', 'institution', '22222222-2222-2222-2222-222222222222', 'INSERT', NULL, 'SYSTEM', NULL, NULL, '{"id": "22222222-2222-2222-2222-222222222222", "status": "PROSPECT", "rssd_id": null, "created_at": "2026-08-14T23:02:12.298016+00:00", "legal_name": "Beta Savings", "updated_at": "2026-08-14T23:02:12.298016+00:00", "fdic_certificate": "FDIC-2002", "institution_type": "SAVINGS_INSTITUTION", "registration_contact_email": "ops@beta.test"}', '2026-08-14 23:02:12.298016+00');
INSERT INTO hazel.audit_log (id, institution_id, entity_type, entity_id, action, changed_by, actor_type, changed_fields, before_data, after_data, occurred_at) OVERRIDING SYSTEM VALUE VALUES (3, '11111111-1111-1111-1111-111111111111', 'app_user', '33333333-3333-3333-3333-333333333333', 'INSERT', NULL, 'SYSTEM', NULL, NULL, '{"id": "33333333-3333-3333-3333-333333333333", "role": "MEMBER_ADMIN", "email": "a@alpha.test", "last_name": "Alpha", "created_at": "2026-08-14T23:02:12.298016+00:00", "first_name": "Ann", "updated_at": "2026-08-14T23:02:12.298016+00:00", "institution_id": "11111111-1111-1111-1111-111111111111", "external_identity_id": "entra-a"}', '2026-08-14 23:02:12.298016+00');
INSERT INTO hazel.audit_log (id, institution_id, entity_type, entity_id, action, changed_by, actor_type, changed_fields, before_data, after_data, occurred_at) OVERRIDING SYSTEM VALUE VALUES (4, '22222222-2222-2222-2222-222222222222', 'app_user', '44444444-4444-4444-4444-444444444444', 'INSERT', NULL, 'SYSTEM', NULL, NULL, '{"id": "44444444-4444-4444-4444-444444444444", "role": "MEMBER_ADMIN", "email": "b@beta.test", "last_name": "Beta", "created_at": "2026-08-14T23:02:12.298016+00:00", "first_name": "Ben", "updated_at": "2026-08-14T23:02:12.298016+00:00", "institution_id": "22222222-2222-2222-2222-222222222222", "external_identity_id": "entra-b"}', '2026-08-14 23:02:12.298016+00');
INSERT INTO hazel.audit_log (id, institution_id, entity_type, entity_id, action, changed_by, actor_type, changed_fields, before_data, after_data, occurred_at) OVERRIDING SYSTEM VALUE VALUES (5, NULL, 'app_user', '55555555-5555-5555-5555-555555555555', 'INSERT', NULL, 'SYSTEM', NULL, NULL, '{"id": "55555555-5555-5555-5555-555555555555", "role": "INTERNAL_REVIEWER", "email": "i@vantage.test", "last_name": "Internal", "created_at": "2026-08-14T23:02:12.298016+00:00", "first_name": "Ivy", "updated_at": "2026-08-14T23:02:12.298016+00:00", "institution_id": null, "external_identity_id": "entra-i"}', '2026-08-14 23:02:12.298016+00');
INSERT INTO hazel.audit_log (id, institution_id, entity_type, entity_id, action, changed_by, actor_type, changed_fields, before_data, after_data, occurred_at) OVERRIDING SYSTEM VALUE VALUES (6, '11111111-1111-1111-1111-111111111111', 'onboarding_case', '66666666-6666-6666-6666-666666666666', 'INSERT', NULL, 'SYSTEM', NULL, NULL, '{"id": "66666666-6666-6666-6666-666666666666", "created_at": "2026-08-14T23:02:12.298016+00:00", "rafa_score": null, "updated_at": "2026-08-14T23:02:12.298016+00:00", "case_number": "HOP-0001", "completed_at": null, "current_stage": "INQUIRY", "current_status": "IN_PROGRESS", "institution_id": "11111111-1111-1111-1111-111111111111", "decision_status": "PENDING", "assessment_outcome": null, "coverbase_vendor_id": null, "inherent_risk_score": null, "coverbase_session_id": null, "coverbase_sync_status": "PENDING", "coverbase_last_synced_at": null, "coverbase_session_status": "NOT_CREATED", "coverbase_questionnaire_id": null, "coverbase_assessment_status": "NOT_STARTED"}', '2026-08-14 23:02:12.298016+00');
INSERT INTO hazel.audit_log (id, institution_id, entity_type, entity_id, action, changed_by, actor_type, changed_fields, before_data, after_data, occurred_at) OVERRIDING SYSTEM VALUE VALUES (7, '22222222-2222-2222-2222-222222222222', 'onboarding_case', '77777777-7777-7777-7777-777777777777', 'INSERT', NULL, 'SYSTEM', NULL, NULL, '{"id": "77777777-7777-7777-7777-777777777777", "created_at": "2026-08-14T23:02:12.298016+00:00", "rafa_score": null, "updated_at": "2026-08-14T23:02:12.298016+00:00", "case_number": "HOP-0002", "completed_at": null, "current_stage": "INQUIRY", "current_status": "IN_PROGRESS", "institution_id": "22222222-2222-2222-2222-222222222222", "decision_status": "PENDING", "assessment_outcome": null, "coverbase_vendor_id": null, "inherent_risk_score": null, "coverbase_session_id": null, "coverbase_sync_status": "PENDING", "coverbase_last_synced_at": null, "coverbase_session_status": "NOT_CREATED", "coverbase_questionnaire_id": null, "coverbase_assessment_status": "NOT_STARTED"}', '2026-08-14 23:02:12.298016+00');


--
-- Data for Name: onboarding_case; Type: TABLE DATA; Schema: hazel; Owner: -
--

INSERT INTO hazel.onboarding_case (id, institution_id, case_number, current_stage, current_status, decision_status, coverbase_session_id, coverbase_vendor_id, coverbase_questionnaire_id, coverbase_session_status, coverbase_assessment_status, coverbase_sync_status, inherent_risk_score, rafa_score, assessment_outcome, coverbase_last_synced_at, created_at, completed_at, updated_at) VALUES ('66666666-6666-6666-6666-666666666666', '11111111-1111-1111-1111-111111111111', 'HOP-0001', 'INQUIRY', 'IN_PROGRESS', 'PENDING', NULL, NULL, NULL, 'NOT_CREATED', 'NOT_STARTED', 'PENDING', NULL, NULL, NULL, NULL, '2026-08-14 23:02:12.298016+00', NULL, '2026-08-14 23:02:12.298016+00');
INSERT INTO hazel.onboarding_case (id, institution_id, case_number, current_stage, current_status, decision_status, coverbase_session_id, coverbase_vendor_id, coverbase_questionnaire_id, coverbase_session_status, coverbase_assessment_status, coverbase_sync_status, inherent_risk_score, rafa_score, assessment_outcome, coverbase_last_synced_at, created_at, completed_at, updated_at) VALUES ('77777777-7777-7777-7777-777777777777', '22222222-2222-2222-2222-222222222222', 'HOP-0002', 'INQUIRY', 'IN_PROGRESS', 'PENDING', NULL, NULL, NULL, 'NOT_CREATED', 'NOT_STARTED', 'PENDING', NULL, NULL, NULL, NULL, '2026-08-14 23:02:12.298016+00', NULL, '2026-08-14 23:02:12.298016+00');


--
-- Data for Name: case_stage_transition; Type: TABLE DATA; Schema: hazel; Owner: -
--

INSERT INTO hazel.case_stage_transition (id, onboarding_case_id, institution_id, from_stage, to_stage, from_status, to_status, actor_type, changed_by, reason, occurred_at) VALUES ('cfb6d363-c2a5-407f-befa-53b2f18d33be', '66666666-6666-6666-6666-666666666666', '11111111-1111-1111-1111-111111111111', NULL, 'INQUIRY', NULL, 'IN_PROGRESS', 'SYSTEM', NULL, NULL, '2026-08-14 23:02:12.298016+00');
INSERT INTO hazel.case_stage_transition (id, onboarding_case_id, institution_id, from_stage, to_stage, from_status, to_status, actor_type, changed_by, reason, occurred_at) VALUES ('b75990f1-20a9-4b1f-88bc-1bb8f6931ada', '77777777-7777-7777-7777-777777777777', '22222222-2222-2222-2222-222222222222', NULL, 'INQUIRY', NULL, 'IN_PROGRESS', 'SYSTEM', NULL, NULL, '2026-08-14 23:02:12.298016+00');


--
-- Data for Name: document; Type: TABLE DATA; Schema: hazel; Owner: -
--



--
-- Data for Name: rafa; Type: TABLE DATA; Schema: hazel; Owner: -
--



--
-- Name: audit_log_id_seq; Type: SEQUENCE SET; Schema: hazel; Owner: -
--

SELECT pg_catalog.setval('hazel.audit_log_id_seq', 27, true);


--
-- PostgreSQL database dump complete
--

\unrestrict C5MAMSCfXGCql0mKi7jBcGeZnLUI3rSqfAIsRp16FVZwhCgsmL8VDAhiXJgKtMq

