-- 03_load_data.sql — wraps 02_data.sql so the copy is faithful.
--
-- Loading 02_data.sql directly fails:
--
--   ERROR: duplicate key value violates unique constraint "audit_log_pkey"
--   DETAIL: Key (id)=(1) already exists.
--
-- Not a dump defect. This schema audits itself: trg_audit fires on every INSERT
-- into institution, user, rafa, onboarding_case and document, writing rows into
-- audit_log with freshly generated identity values. So restoring the *source's*
-- audit history collides with the audit history the restore itself is generating.
-- trg_stage_history does the same to case_stage_transition.
--
-- Disabling user triggers for the load is therefore not a workaround, it is the
-- only way to reproduce the source: the alternative keeps the triggers and stores
-- a history describing the restore instead of a history describing what happened.
--
-- DISABLE TRIGGER USER, not DISABLE TRIGGER ALL: the latter also disables the
-- internal constraint triggers that enforce foreign keys, which would let a
-- broken referential state load silently.
--
-- Run with: psql -v ON_ERROR_STOP=1 -f 03_load_data.sql

BEGIN;

ALTER TABLE hazel.institution           DISABLE TRIGGER USER;
ALTER TABLE hazel."user"                DISABLE TRIGGER USER;
ALTER TABLE hazel.rafa                  DISABLE TRIGGER USER;
ALTER TABLE hazel.onboarding_case       DISABLE TRIGGER USER;
ALTER TABLE hazel.document              DISABLE TRIGGER USER;
ALTER TABLE hazel.case_stage_transition DISABLE TRIGGER USER;
ALTER TABLE hazel.audit_log             DISABLE TRIGGER USER;

-- Idempotent: clears any partial load, including audit rows a failed attempt
-- generated. CASCADE because the tables reference each other.
TRUNCATE hazel.audit_log, hazel.case_stage_transition, hazel.document,
         hazel.onboarding_case, hazel.rafa, hazel."user", hazel.institution CASCADE;

\i 02_data.sql

ALTER TABLE hazel.institution           ENABLE TRIGGER USER;
ALTER TABLE hazel."user"                ENABLE TRIGGER USER;
ALTER TABLE hazel.rafa                  ENABLE TRIGGER USER;
ALTER TABLE hazel.onboarding_case       ENABLE TRIGGER USER;
ALTER TABLE hazel.document              ENABLE TRIGGER USER;
ALTER TABLE hazel.case_stage_transition ENABLE TRIGGER USER;
ALTER TABLE hazel.audit_log             ENABLE TRIGGER USER;

-- No setval here, deliberately. 02_data.sql already ends with one carrying the
-- SOURCE sequence position, and that is not the same as max(id):
--
--     source   audit_log_id_seq = 27,  max(id) = 7
--
-- because ids were consumed by rows since deleted. An earlier revision of this
-- file reset the sequence to max(id), which looked like tidying up and silently
-- made the copy diverge from the source it claims to reproduce.
--
-- The guard below fires only if the restore left the sequence BEHIND max(id),
-- which would break the next audited write. It never moves the sequence back.
SELECT setval(pg_get_serial_sequence('hazel.audit_log', 'id'), s.mx)
  FROM (SELECT max(id) AS mx FROM hazel.audit_log) s
 WHERE s.mx IS NOT NULL
   AND (SELECT last_value FROM hazel.audit_log_id_seq) < s.mx;

COMMIT;
