-- =====================================================================
-- Hazel Operations Portal (HOP) - Lakebase Postgres schema
-- Target: PostgreSQL 17 (Databricks Lakebase).  Validated on 16.13.
-- Clean replacement: drops and recreates the `hazel` schema.
--
-- Session contract - the API MUST set these per transaction:
--   SELECT set_config('hop.institution_id', $1, true);
--   SELECT set_config('hop.user_id',        $2, true);
--   SELECT set_config('hop.role',           $3, true);
-- `hop.role` carries either a hazel."user".role value or the literal
-- 'SYSTEM' for anonymous intake (public inquiry form).
-- =====================================================================

-- ---------------------------------------------------------------------
-- 0.  SCHEMA AND APPLICATION ROLE
-- ---------------------------------------------------------------------
DROP SCHEMA IF EXISTS hazel CASCADE;
CREATE SCHEMA hazel;

-- Idempotent: the Lakebase SQL editor stops at the first error and
-- silently skips every statement after it, so never let this throw.
DO $do$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hop_app') THEN
    CREATE ROLE hop_app NOLOGIN NOBYPASSRLS;
  END IF;
END
$do$;

-- ---------------------------------------------------------------------
-- 1.  SESSION HELPERS  (used by RLS policies and triggers)
--     nullif(...) so an unset variable is NULL, not an empty-string cast
--     error.  Unset context therefore fails closed.
-- ---------------------------------------------------------------------
CREATE FUNCTION hazel.current_institution() RETURNS uuid
  LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('hop.institution_id', true), '')::uuid $$;

CREATE FUNCTION hazel.current_user_id() RETURNS uuid
  LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('hop.user_id', true), '')::uuid $$;

-- starts_with(), not LIKE 'INTERNAL_%' - underscore is a LIKE wildcard.
CREATE FUNCTION hazel.is_internal() RETURNS boolean
  LANGUAGE sql STABLE AS
$$ SELECT starts_with(coalesce(nullif(current_setting('hop.role', true), ''), ''), 'INTERNAL_') $$;

CREATE FUNCTION hazel.is_system() RETURNS boolean
  LANGUAGE sql STABLE AS
$$ SELECT coalesce(nullif(current_setting('hop.role', true), ''), '') = 'SYSTEM' $$;

-- ---------------------------------------------------------------------
-- 2.  TABLES
-- ---------------------------------------------------------------------

-- 2.1 institution ------------------------------------------------------
CREATE TABLE hazel.institution (
  id                         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  legal_name                 text NOT NULL,
  fdic_certificate           text,
  rssd_id                    text,          -- MAINTAINED COPY from hazel.rafa
  institution_type           text NOT NULL DEFAULT 'OTHER',
  status                     text NOT NULL DEFAULT 'PROSPECT',
  registration_contact_email text NOT NULL,
  created_at                 timestamptz NOT NULL DEFAULT now(),
  updated_at                 timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_institution_type CHECK (institution_type IN
    ('NATIONAL_BANK','STATE_MEMBER_BANK','STATE_NONMEMBER_BANK',
     'SAVINGS_INSTITUTION','CREDIT_UNION','TRUST_COMPANY','OTHER')),
  CONSTRAINT ck_institution_status CHECK (status IN
    ('PROSPECT','ONBOARDING','ACTIVE','SUSPENDED','DECLINED','WITHDRAWN'))
);
COMMENT ON COLUMN hazel.institution.rssd_id IS
  'Maintained copy of hazel.rafa.rssd_id. Written only by fn_propagate_rafa; hop_app has no UPDATE privilege on this column.';

-- 2.2 user -------------------------------------------------------------
-- The deployed table is hazel."user", so every reference below is quoted.
-- Bare `user` is a reserved word: an unqualified `FROM user` is a syntax
-- error, which makes the quoting permanent rather than stylistic.
--
-- The live primary key index is named app_user_pkey, because the table was
-- created under that name and renamed; Postgres keeps index names across a
-- rename. A fresh run of this file names it user_pkey instead. That differs
-- from the deployed database in name only and has no functional effect.
CREATE TABLE hazel."user" (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id       uuid REFERENCES hazel.institution(id) ON DELETE RESTRICT,
  external_identity_id text NOT NULL,       -- Microsoft Entra object id
  email                text NOT NULL,
  first_name           text,
  last_name            text,
  role                 text NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_user_external_identity UNIQUE (external_identity_id),
  CONSTRAINT uq_user_email             UNIQUE (email),
  CONSTRAINT ck_user_role CHECK (role IN
    ('MEMBER_ADMIN','MEMBER_CONTRIBUTOR','MEMBER_VIEWER',
     'INTERNAL_REVIEWER','INTERNAL_RISK','INTERNAL_APPROVER',
     'INTERNAL_ADMIN','INTERNAL_SUPPORT')),
  -- internal staff belong to no institution; member users must have one
  CONSTRAINT ck_user_scope CHECK (
    (starts_with(role,'INTERNAL_') AND institution_id IS NULL) OR
    (starts_with(role,'MEMBER_')   AND institution_id IS NOT NULL))
);

-- 2.3 rafa -------------------------------------------------------------
-- System of record is the RAFA platform. This is a local projection.
CREATE TABLE hazel.rafa (
  institution_id   uuid PRIMARY KEY REFERENCES hazel.institution(id) ON DELETE CASCADE,
  fdic_certificate text,
  rssd_id          text,
  rafa_score       numeric(5,2),
  rafa_status      text NOT NULL DEFAULT 'NOT_SCREENED',
  fetched_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_rafa_status CHECK (rafa_status IN
    ('NOT_SCREENED','PENDING','PASS','PROOF_REQUIRED','DECLINE','ERROR')),
  CONSTRAINT ck_rafa_score CHECK (rafa_score IS NULL OR rafa_score >= 0)
);
COMMENT ON TABLE hazel.rafa IS
  'Projection of the RAFA platform result. fetched_at records when it was pulled, so staleness is visible.';

-- 2.4 onboarding_case --------------------------------------------------
CREATE TABLE hazel.onboarding_case (
  id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id              uuid NOT NULL REFERENCES hazel.institution(id) ON DELETE RESTRICT,
  case_number                 text NOT NULL,
  current_stage               text NOT NULL DEFAULT 'INQUIRY',
  current_status              text NOT NULL DEFAULT 'IN_PROGRESS',
  decision_status             text NOT NULL DEFAULT 'PENDING',
  coverbase_session_id        text,
  coverbase_vendor_id         text,
  coverbase_questionnaire_id  text,
  coverbase_session_status    text NOT NULL DEFAULT 'NOT_CREATED',
  coverbase_assessment_status text NOT NULL DEFAULT 'NOT_STARTED',
  coverbase_sync_status       text NOT NULL DEFAULT 'PENDING',
  inherent_risk_score         numeric(5,2),
  rafa_score                  integer,        -- MAINTAINED COPY from hazel.rafa.
                                              -- integer here, numeric(5,2) there;
                                              -- fn_propagate_rafa rounds on copy.
  assessment_outcome          text,
  coverbase_last_synced_at    timestamptz,
  created_at                  timestamptz NOT NULL DEFAULT now(),
  completed_at                timestamptz DEFAULT now(),
  updated_at                  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_case_number UNIQUE (case_number),
  -- target for the composite foreign keys on document and transitions
  CONSTRAINT uq_case_id_institution UNIQUE (id, institution_id),
  CONSTRAINT ck_case_stage CHECK (current_stage IN
    ('INQUIRY','ELIGIBILITY_SCREENING','NDA',
     'RISK_ASSESSMENT','VANTAGE_REVIEW','ACCOUNT_OPENING','COMPLETED')),
  CONSTRAINT ck_case_status CHECK (current_status IN
    ('IN_PROGRESS','AWAITING_MEMBER','AWAITING_VANTAGE',
     'ON_HOLD','COMPLETED','DECLINED')),
  CONSTRAINT ck_case_decision CHECK (decision_status IN
    ('PENDING','APPROVED','DECLINED','MORE_INFO_REQUIRED')),
  CONSTRAINT ck_cb_session_status CHECK (coverbase_session_status IN
    ('NOT_CREATED','CREATED','IN_PROGRESS','SUBMITTED','EXPIRED','CANCELLED')),
  CONSTRAINT ck_cb_assessment_status CHECK (coverbase_assessment_status IN
    ('NOT_STARTED','PENDING','IN_REVIEW','COMPLETED','FAILED')),
  CONSTRAINT ck_cb_sync_status CHECK (coverbase_sync_status IN
    ('PENDING','IN_PROGRESS','SYNCED','FAILED','RETRYING','NOT_APPLICABLE')),
  CONSTRAINT ck_case_outcome CHECK (assessment_outcome IS NULL OR assessment_outcome IN
    ('LOW','MODERATE','HIGH','CRITICAL')),
  CONSTRAINT ck_case_scores CHECK (
    (inherent_risk_score IS NULL OR inherent_risk_score >= 0) AND
    (rafa_score          IS NULL OR rafa_score          >= 0)),
  CONSTRAINT ck_case_completed_after_created CHECK (
    completed_at IS NULL OR completed_at >= created_at)
);
COMMENT ON COLUMN hazel.onboarding_case.rafa_score IS
  'Maintained copy of hazel.rafa.rafa_score. Written only by fn_propagate_rafa; hop_app has no UPDATE privilege on this column.';

-- one active case per institution
CREATE UNIQUE INDEX ux_case_one_active ON hazel.onboarding_case (institution_id)
  WHERE current_status NOT IN ('COMPLETED','WITHDRAWN','DECLINED');

-- 2.5 document ---------------------------------------------------------
-- Bytes live in the Unity Catalog Volume at file_path; this row is the
-- metadata. institution_id is enforced by composite FK against the case.
CREATE TABLE hazel.document (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id        uuid NOT NULL,
  onboarding_case_id    uuid NOT NULL,
  uploaded_by           uuid NOT NULL REFERENCES hazel."user"(id) ON DELETE RESTRICT,
  document_type_name    text NOT NULL,
  file_name             text NOT NULL,
  file_path             text NOT NULL,
  file_size_bytes       bigint,
  sha256                text,
  reference_document_id jsonb NOT NULL DEFAULT '{}'::jsonb,
  sync_status           text NOT NULL DEFAULT 'PENDING',
  review_status         text NOT NULL DEFAULT 'PENDING_REVIEW',
  uploaded_at           timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_document_case FOREIGN KEY (onboarding_case_id, institution_id)
    REFERENCES hazel.onboarding_case (id, institution_id) ON DELETE RESTRICT,
  CONSTRAINT ck_document_type CHECK (document_type_name IN
    ('NDA','CBDDQ','BSA_AML_POLICY','FINANCIAL_STATEMENTS','ORG_CHART',
     'INFOSEC_POLICY','BCP_DR_PLAN','INSURANCE_CERT','SOC2_REPORT',
     'COMPLIANCE_MANUAL','SIGNED_AGREEMENT','OTHER')),
  CONSTRAINT ck_document_sync CHECK (sync_status IN
    ('PENDING','IN_PROGRESS','SYNCED','FAILED','RETRYING','NOT_APPLICABLE')),
  CONSTRAINT ck_document_review CHECK (review_status IN
    ('PENDING_REVIEW','IN_REVIEW','ACCEPTED','REJECTED')),
  CONSTRAINT ck_document_size CHECK (file_size_bytes IS NULL OR file_size_bytes > 0),
  CONSTRAINT ck_document_sha CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$')
);
COMMENT ON COLUMN hazel.document.file_path IS
  '/Volumes/hazel/onboarding/uploads/{institution_id}/{onboarding_case_id}/{document_id}.{ext}';

-- 2.6 case_stage_transition  (append-only, trigger-written) ------------
CREATE TABLE hazel.case_stage_transition (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  onboarding_case_id uuid NOT NULL,
  institution_id     uuid NOT NULL,
  from_stage         text,
  to_stage           text NOT NULL,
  from_status        text,
  to_status          text NOT NULL,
  actor_type         text NOT NULL,
  changed_by         uuid REFERENCES hazel."user"(id) ON DELETE RESTRICT,
  reason             text,
  occurred_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_transition_case FOREIGN KEY (onboarding_case_id, institution_id)
    REFERENCES hazel.onboarding_case (id, institution_id) ON DELETE RESTRICT,
  CONSTRAINT ck_transition_actor_type CHECK (actor_type IN ('USER','SYSTEM','WEBHOOK','JOB')),
  -- a USER-attributed row must name the user, or attribution is a lie
  CONSTRAINT ck_transition_actor CHECK (actor_type <> 'USER' OR changed_by IS NOT NULL),
  -- a transition must actually change something
  CONSTRAINT ck_transition_changed CHECK (
    from_stage IS DISTINCT FROM to_stage OR from_status IS DISTINCT FROM to_status)
);

-- 2.7 audit_log  (append-only, trigger-written) ------------------------
CREATE TABLE hazel.audit_log (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  institution_id uuid REFERENCES hazel.institution(id) ON DELETE RESTRICT,
  entity_type    text NOT NULL,
  entity_id      uuid NOT NULL,
  action         text NOT NULL,
  changed_by     uuid REFERENCES hazel."user"(id) ON DELETE RESTRICT,
  actor_type     text NOT NULL,
  changed_fields text[],
  before_data    jsonb,
  after_data     jsonb,
  occurred_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_audit_action CHECK (action IN ('INSERT','UPDATE','DELETE')),
  CONSTRAINT ck_audit_actor_type CHECK (actor_type IN ('USER','SYSTEM','WEBHOOK','JOB')),
  CONSTRAINT ck_audit_actor CHECK (actor_type <> 'USER' OR changed_by IS NOT NULL)
);

-- ---------------------------------------------------------------------
-- 3.  INDEXES  (every FK column, plus the query paths the portal uses)
-- ---------------------------------------------------------------------
CREATE UNIQUE INDEX ux_institution_fdic ON hazel.institution (fdic_certificate)
  WHERE fdic_certificate IS NOT NULL;

CREATE INDEX ix_user_institution     ON hazel."user" (institution_id);
CREATE INDEX ix_case_institution     ON hazel.onboarding_case (institution_id);
CREATE INDEX ix_case_stage_status    ON hazel.onboarding_case (current_stage, current_status);
CREATE INDEX ix_document_institution ON hazel.document (institution_id);
CREATE INDEX ix_document_case        ON hazel.document (onboarding_case_id);
CREATE INDEX ix_document_uploader    ON hazel.document (uploaded_by);
CREATE INDEX ix_document_type        ON hazel.document (document_type_name);
CREATE INDEX ix_transition_case      ON hazel.case_stage_transition (onboarding_case_id, occurred_at DESC);
CREATE INDEX ix_transition_inst      ON hazel.case_stage_transition (institution_id);
CREATE INDEX ix_transition_actor     ON hazel.case_stage_transition (changed_by);
CREATE INDEX ix_audit_entity         ON hazel.audit_log (entity_type, entity_id, occurred_at DESC);
CREATE INDEX ix_audit_institution    ON hazel.audit_log (institution_id, occurred_at DESC);
CREATE INDEX ix_audit_actor          ON hazel.audit_log (changed_by);

-- ---------------------------------------------------------------------
-- 4.  TRIGGER FUNCTIONS
-- ---------------------------------------------------------------------

-- 4.1 updated_at -------------------------------------------------------
CREATE FUNCTION hazel.fn_touch_updated_at() RETURNS trigger
  LANGUAGE plpgsql AS $fn$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END
$fn$;

-- 4.2 stage history ----------------------------------------------------
-- Written by the database, not the application: history that depends on
-- the app remembering to write it goes missing exactly when it matters.
CREATE FUNCTION hazel.fn_log_stage_transition() RETURNS trigger
  LANGUAGE plpgsql SECURITY DEFINER AS $fn$
DECLARE
  v_actor  uuid := hazel.current_user_id();
  v_type   text := CASE WHEN hazel.current_user_id() IS NOT NULL THEN 'USER' ELSE 'SYSTEM' END;
  v_reason text := nullif(current_setting('hop.transition_reason', true), '');
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO hazel.case_stage_transition
      (onboarding_case_id, institution_id, from_stage, to_stage,
       from_status, to_status, actor_type, changed_by, reason)
    VALUES (NEW.id, NEW.institution_id, NULL, NEW.current_stage,
            NULL, NEW.current_status, v_type, v_actor, v_reason);

  ELSIF NEW.current_stage  IS DISTINCT FROM OLD.current_stage
     OR NEW.current_status IS DISTINCT FROM OLD.current_status THEN
    INSERT INTO hazel.case_stage_transition
      (onboarding_case_id, institution_id, from_stage, to_stage,
       from_status, to_status, actor_type, changed_by, reason)
    VALUES (NEW.id, NEW.institution_id, OLD.current_stage, NEW.current_stage,
            OLD.current_status, NEW.current_status, v_type, v_actor, v_reason);
  END IF;
  RETURN NULL;
END
$fn$;

-- 4.3 generic audit ----------------------------------------------------
-- Table-agnostic: uses TG_TABLE_NAME and to_jsonb(), so columns added
-- later are captured without touching this function.
CREATE FUNCTION hazel.fn_audit() RETURNS trigger
  LANGUAGE plpgsql SECURITY DEFINER AS $fn$
DECLARE
  v_before  jsonb;
  v_after   jsonb;
  v_changed text[];
  v_entity  uuid;
  v_inst    uuid;
  v_actor   uuid := hazel.current_user_id();
  v_type    text := CASE WHEN hazel.current_user_id() IS NOT NULL THEN 'USER' ELSE 'SYSTEM' END;
BEGIN
  IF    TG_OP = 'DELETE' THEN v_before := to_jsonb(OLD);
  ELSIF TG_OP = 'INSERT' THEN v_after  := to_jsonb(NEW);
  ELSE  v_before := to_jsonb(OLD); v_after := to_jsonb(NEW);
  END IF;

  IF TG_OP = 'UPDATE' THEN
    SELECT array_agg(e.key ORDER BY e.key) INTO v_changed
    FROM jsonb_each(v_after) e
    WHERE e.value IS DISTINCT FROM v_before -> e.key;
  END IF;

  -- institution and rafa are keyed by the institution itself
  IF TG_TABLE_NAME = 'rafa' THEN
    v_entity := coalesce((v_after->>'institution_id')::uuid, (v_before->>'institution_id')::uuid);
    v_inst   := v_entity;
  ELSIF TG_TABLE_NAME = 'institution' THEN
    v_entity := coalesce((v_after->>'id')::uuid, (v_before->>'id')::uuid);
    v_inst   := v_entity;
  ELSE
    v_entity := coalesce((v_after->>'id')::uuid, (v_before->>'id')::uuid);
    v_inst   := coalesce((v_after->>'institution_id')::uuid, (v_before->>'institution_id')::uuid);
  END IF;

  INSERT INTO hazel.audit_log
    (institution_id, entity_type, entity_id, action, changed_by,
     actor_type, changed_fields, before_data, after_data)
  VALUES (v_inst, TG_TABLE_NAME, v_entity, TG_OP, v_actor,
          v_type, v_changed, v_before, v_after);
  RETURN NULL;
END
$fn$;

-- 4.4 RAFA propagation -------------------------------------------------
-- SECURITY DEFINER so it runs as the schema owner, who holds UPDATE on
-- the protected columns.  hop_app does not, so these copies cannot drift.
CREATE FUNCTION hazel.fn_propagate_rafa() RETURNS trigger
  LANGUAGE plpgsql SECURITY DEFINER AS $fn$
BEGIN
  UPDATE hazel.institution
     SET rssd_id = NEW.rssd_id
   WHERE id = NEW.institution_id
     AND rssd_id IS DISTINCT FROM NEW.rssd_id;

  UPDATE hazel.onboarding_case
     SET rafa_score = NEW.rafa_score
   WHERE institution_id = NEW.institution_id
     AND rafa_score IS DISTINCT FROM NEW.rafa_score;

  RETURN NULL;
END
$fn$;

-- 4.5 uploader check ---------------------------------------------------
-- The composite FK guarantees the document matches its case.  This
-- guarantees the uploader matches too, while still allowing internal
-- reviewers (who belong to no institution) to upload on a bank's behalf.
CREATE FUNCTION hazel.fn_check_uploader() RETURNS trigger
  LANGUAGE plpgsql SECURITY DEFINER AS $fn$
DECLARE
  v_inst uuid;
  v_role text;
BEGIN
  SELECT institution_id, role INTO v_inst, v_role
    FROM hazel."user" WHERE id = NEW.uploaded_by;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'uploader % does not exist', NEW.uploaded_by;
  END IF;

  IF starts_with(v_role, 'INTERNAL_') THEN
    RETURN NEW;                       -- internal staff may upload anywhere
  END IF;

  IF v_inst IS DISTINCT FROM NEW.institution_id THEN
    RAISE EXCEPTION
      'uploader % belongs to institution %, but the document is for institution %',
      NEW.uploaded_by, v_inst, NEW.institution_id;
  END IF;

  RETURN NEW;
END
$fn$;

-- ---------------------------------------------------------------------
-- 5.  TRIGGERS
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_touch BEFORE UPDATE ON hazel.institution
  FOR EACH ROW EXECUTE FUNCTION hazel.fn_touch_updated_at();
CREATE TRIGGER trg_touch BEFORE UPDATE ON hazel."user"
  FOR EACH ROW EXECUTE FUNCTION hazel.fn_touch_updated_at();
CREATE TRIGGER trg_touch BEFORE UPDATE ON hazel.rafa
  FOR EACH ROW EXECUTE FUNCTION hazel.fn_touch_updated_at();
CREATE TRIGGER trg_touch BEFORE UPDATE ON hazel.onboarding_case
  FOR EACH ROW EXECUTE FUNCTION hazel.fn_touch_updated_at();
CREATE TRIGGER trg_touch BEFORE UPDATE ON hazel.document
  FOR EACH ROW EXECUTE FUNCTION hazel.fn_touch_updated_at();

CREATE TRIGGER trg_stage_history AFTER INSERT OR UPDATE ON hazel.onboarding_case
  FOR EACH ROW EXECUTE FUNCTION hazel.fn_log_stage_transition();

CREATE TRIGGER trg_propagate AFTER INSERT OR UPDATE ON hazel.rafa
  FOR EACH ROW EXECUTE FUNCTION hazel.fn_propagate_rafa();

CREATE TRIGGER trg_uploader BEFORE INSERT OR UPDATE ON hazel.document
  FOR EACH ROW EXECUTE FUNCTION hazel.fn_check_uploader();

CREATE TRIGGER trg_audit AFTER INSERT OR UPDATE OR DELETE ON hazel.institution
  FOR EACH ROW EXECUTE FUNCTION hazel.fn_audit();
CREATE TRIGGER trg_audit AFTER INSERT OR UPDATE OR DELETE ON hazel."user"
  FOR EACH ROW EXECUTE FUNCTION hazel.fn_audit();
CREATE TRIGGER trg_audit AFTER INSERT OR UPDATE OR DELETE ON hazel.rafa
  FOR EACH ROW EXECUTE FUNCTION hazel.fn_audit();
CREATE TRIGGER trg_audit AFTER INSERT OR UPDATE OR DELETE ON hazel.onboarding_case
  FOR EACH ROW EXECUTE FUNCTION hazel.fn_audit();
CREATE TRIGGER trg_audit AFTER INSERT OR UPDATE OR DELETE ON hazel.document
  FOR EACH ROW EXECUTE FUNCTION hazel.fn_audit();

-- ---------------------------------------------------------------------
-- 6.  PRIVILEGES
--     UPDATE is granted COLUMN BY COLUMN on the two tables holding
--     maintained copies.  A table-level GRANT followed by a column-level
--     REVOKE does NOT work - the revoke is a silent no-op.
-- ---------------------------------------------------------------------
GRANT USAGE ON SCHEMA hazel TO hop_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA hazel TO hop_app;

-- institution: no UPDATE on rssd_id
GRANT SELECT, INSERT, DELETE ON hazel.institution TO hop_app;
GRANT UPDATE (legal_name, fdic_certificate, institution_type, status,
              registration_contact_email, updated_at)
  ON hazel.institution TO hop_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON hazel."user"   TO hop_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON hazel.rafa     TO hop_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON hazel.document TO hop_app;

-- onboarding_case: no UPDATE on rafa_score
GRANT SELECT, INSERT, DELETE ON hazel.onboarding_case TO hop_app;
GRANT UPDATE (case_number, current_stage, current_status, decision_status,
              coverbase_session_id, coverbase_vendor_id, coverbase_questionnaire_id,
              coverbase_session_status, coverbase_assessment_status,
              coverbase_sync_status, inherent_risk_score, assessment_outcome,
              coverbase_last_synced_at, completed_at, updated_at)
  ON hazel.onboarding_case TO hop_app;

-- append-only: INSERT and SELECT, never UPDATE or DELETE
GRANT SELECT, INSERT ON hazel.case_stage_transition TO hop_app;
GRANT SELECT, INSERT ON hazel.audit_log             TO hop_app;

-- ---------------------------------------------------------------------
-- 7.  ROW LEVEL SECURITY
--     FORCE so the table owner is subject to the policies too.
--     WITH CHECK mirrors USING so a cross-tenant write is REJECTED,
--     not silently discarded.
-- ---------------------------------------------------------------------
ALTER TABLE hazel.institution           ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel.institution           FORCE  ROW LEVEL SECURITY;
ALTER TABLE hazel."user"                ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel."user"                FORCE  ROW LEVEL SECURITY;
ALTER TABLE hazel.rafa                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel.rafa                  FORCE  ROW LEVEL SECURITY;
ALTER TABLE hazel.onboarding_case       ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel.onboarding_case       FORCE  ROW LEVEL SECURITY;
ALTER TABLE hazel.document              ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel.document              FORCE  ROW LEVEL SECURITY;
ALTER TABLE hazel.case_stage_transition ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel.case_stage_transition FORCE  ROW LEVEL SECURITY;
ALTER TABLE hazel.audit_log             ENABLE ROW LEVEL SECURITY;
ALTER TABLE hazel.audit_log             FORCE  ROW LEVEL SECURITY;

-- institution is keyed on id, not institution_id
CREATE POLICY p_tenant ON hazel.institution
  USING      (hazel.is_internal() OR id = hazel.current_institution())
  WITH CHECK (hazel.is_internal() OR id = hazel.current_institution());

CREATE POLICY p_tenant ON hazel."user"
  USING      (hazel.is_internal() OR institution_id = hazel.current_institution())
  WITH CHECK (hazel.is_internal() OR institution_id = hazel.current_institution());

CREATE POLICY p_tenant ON hazel.rafa
  USING      (hazel.is_internal() OR institution_id = hazel.current_institution())
  WITH CHECK (hazel.is_internal() OR institution_id = hazel.current_institution());

CREATE POLICY p_tenant ON hazel.onboarding_case
  USING      (hazel.is_internal() OR institution_id = hazel.current_institution())
  WITH CHECK (hazel.is_internal() OR institution_id = hazel.current_institution());

CREATE POLICY p_tenant ON hazel.document
  USING      (hazel.is_internal() OR institution_id = hazel.current_institution())
  WITH CHECK (hazel.is_internal() OR institution_id = hazel.current_institution());

CREATE POLICY p_tenant ON hazel.case_stage_transition
  USING      (hazel.is_internal() OR institution_id = hazel.current_institution())
  WITH CHECK (hazel.is_internal() OR institution_id = hazel.current_institution()
              OR hazel.is_system());

CREATE POLICY p_tenant ON hazel.audit_log
  USING      (hazel.is_internal() OR institution_id = hazel.current_institution())
  WITH CHECK (hazel.is_internal() OR institution_id = hazel.current_institution()
              OR hazel.is_system());

-- Anonymous intake: the public inquiry form creates an institution, its
-- first user and a case before anyone has logged in.  Permissive policies
-- are OR'd, so this adds an INSERT-only path for hop.role = 'SYSTEM'.
CREATE POLICY p_intake ON hazel.institution     FOR INSERT WITH CHECK (hazel.is_system());
CREATE POLICY p_intake ON hazel."user"          FOR INSERT WITH CHECK (hazel.is_system());
CREATE POLICY p_intake ON hazel.onboarding_case FOR INSERT WITH CHECK (hazel.is_system());
