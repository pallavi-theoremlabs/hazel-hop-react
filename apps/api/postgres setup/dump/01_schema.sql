--
-- PostgreSQL database dump
--

\restrict wF1Qs5HhTdmU8xcfTb3xstDsxPK9QJ4r8X1om8mntTQvkNajrgCETVSZFQmtMfV

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
-- Name: hazel; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA hazel;


--
-- Name: current_institution(); Type: FUNCTION; Schema: hazel; Owner: -
--

CREATE FUNCTION hazel.current_institution() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$ SELECT nullif(current_setting('hop.institution_id', true), '')::uuid $$;


--
-- Name: current_user_id(); Type: FUNCTION; Schema: hazel; Owner: -
--

CREATE FUNCTION hazel.current_user_id() RETURNS uuid
    LANGUAGE sql STABLE
    AS $$ SELECT nullif(current_setting('hop.user_id', true), '')::uuid $$;


--
-- Name: fn_audit(); Type: FUNCTION; Schema: hazel; Owner: -
--

CREATE FUNCTION hazel.fn_audit() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
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
$$;


--
-- Name: fn_check_uploader(); Type: FUNCTION; Schema: hazel; Owner: -
--

CREATE FUNCTION hazel.fn_check_uploader() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
  v_inst uuid;
  v_role text;
BEGIN
  SELECT institution_id, role INTO v_inst, v_role
    FROM hazel.app_user WHERE id = NEW.uploaded_by;

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
$$;


--
-- Name: fn_log_stage_transition(); Type: FUNCTION; Schema: hazel; Owner: -
--

CREATE FUNCTION hazel.fn_log_stage_transition() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
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
$$;


--
-- Name: fn_propagate_rafa(); Type: FUNCTION; Schema: hazel; Owner: -
--

CREATE FUNCTION hazel.fn_propagate_rafa() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
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
$$;


--
-- Name: fn_touch_updated_at(); Type: FUNCTION; Schema: hazel; Owner: -
--

CREATE FUNCTION hazel.fn_touch_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END
$$;


--
-- Name: is_internal(); Type: FUNCTION; Schema: hazel; Owner: -
--

CREATE FUNCTION hazel.is_internal() RETURNS boolean
    LANGUAGE sql STABLE
    AS $$ SELECT starts_with(coalesce(nullif(current_setting('hop.role', true), ''), ''), 'INTERNAL_') $$;


--
-- Name: is_system(); Type: FUNCTION; Schema: hazel; Owner: -
--

CREATE FUNCTION hazel.is_system() RETURNS boolean
    LANGUAGE sql STABLE
    AS $$ SELECT coalesce(nullif(current_setting('hop.role', true), ''), '') = 'SYSTEM' $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_log; Type: TABLE; Schema: hazel; Owner: -
--

CREATE TABLE hazel.audit_log (
    id bigint NOT NULL,
    institution_id uuid,
    entity_type text NOT NULL,
    entity_id uuid NOT NULL,
    action text NOT NULL,
    changed_by uuid,
    actor_type text NOT NULL,
    changed_fields text[],
    before_data jsonb,
    after_data jsonb,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_audit_action CHECK ((action = ANY (ARRAY['INSERT'::text, 'UPDATE'::text, 'DELETE'::text]))),
    CONSTRAINT ck_audit_actor CHECK (((actor_type <> 'USER'::text) OR (changed_by IS NOT NULL))),
    CONSTRAINT ck_audit_actor_type CHECK ((actor_type = ANY (ARRAY['USER'::text, 'SYSTEM'::text, 'WEBHOOK'::text, 'JOB'::text])))
);

ALTER TABLE ONLY hazel.audit_log FORCE ROW LEVEL SECURITY;


--
-- Name: audit_log_id_seq; Type: SEQUENCE; Schema: hazel; Owner: -
--

ALTER TABLE hazel.audit_log ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME hazel.audit_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: case_stage_transition; Type: TABLE; Schema: hazel; Owner: -
--

CREATE TABLE hazel.case_stage_transition (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    onboarding_case_id uuid NOT NULL,
    institution_id uuid NOT NULL,
    from_stage text,
    to_stage text NOT NULL,
    from_status text,
    to_status text NOT NULL,
    actor_type text NOT NULL,
    changed_by uuid,
    reason text,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_transition_actor CHECK (((actor_type <> 'USER'::text) OR (changed_by IS NOT NULL))),
    CONSTRAINT ck_transition_actor_type CHECK ((actor_type = ANY (ARRAY['USER'::text, 'SYSTEM'::text, 'WEBHOOK'::text, 'JOB'::text]))),
    CONSTRAINT ck_transition_changed CHECK (((from_stage IS DISTINCT FROM to_stage) OR (from_status IS DISTINCT FROM to_status)))
);

ALTER TABLE ONLY hazel.case_stage_transition FORCE ROW LEVEL SECURITY;


--
-- Name: document; Type: TABLE; Schema: hazel; Owner: -
--

CREATE TABLE hazel.document (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    institution_id uuid NOT NULL,
    onboarding_case_id uuid NOT NULL,
    uploaded_by uuid NOT NULL,
    document_type_name text NOT NULL,
    file_name text NOT NULL,
    file_path text NOT NULL,
    file_size_bytes bigint,
    sha256 text,
    reference_document_id jsonb DEFAULT '{}'::jsonb NOT NULL,
    sync_status text DEFAULT 'PENDING'::text NOT NULL,
    review_status text DEFAULT 'PENDING_REVIEW'::text NOT NULL,
    uploaded_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_document_review CHECK ((review_status = ANY (ARRAY['PENDING_REVIEW'::text, 'IN_REVIEW'::text, 'ACCEPTED'::text, 'REJECTED'::text]))),
    CONSTRAINT ck_document_sha CHECK (((sha256 IS NULL) OR (sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT ck_document_size CHECK (((file_size_bytes IS NULL) OR (file_size_bytes > 0))),
    CONSTRAINT ck_document_sync CHECK ((sync_status = ANY (ARRAY['PENDING'::text, 'IN_PROGRESS'::text, 'SYNCED'::text, 'FAILED'::text, 'RETRYING'::text, 'NOT_APPLICABLE'::text]))),
    CONSTRAINT ck_document_type CHECK ((document_type_name = ANY (ARRAY['NDA'::text, 'CBDDQ'::text, 'BSA_AML_POLICY'::text, 'FINANCIAL_STATEMENTS'::text, 'ORG_CHART'::text, 'INFOSEC_POLICY'::text, 'BCP_DR_PLAN'::text, 'INSURANCE_CERT'::text, 'SOC2_REPORT'::text, 'COMPLIANCE_MANUAL'::text, 'SIGNED_AGREEMENT'::text, 'OTHER'::text])))
);

ALTER TABLE ONLY hazel.document FORCE ROW LEVEL SECURITY;


--
-- Name: COLUMN document.file_path; Type: COMMENT; Schema: hazel; Owner: -
--

COMMENT ON COLUMN hazel.document.file_path IS '/Volumes/hazel/onboarding/uploads/{institution_id}/{onboarding_case_id}/{document_id}.{ext}';


--
-- Name: institution; Type: TABLE; Schema: hazel; Owner: -
--

CREATE TABLE hazel.institution (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    legal_name text NOT NULL,
    fdic_certificate text,
    rssd_id text,
    institution_type text DEFAULT 'OTHER'::text NOT NULL,
    status text DEFAULT 'PROSPECT'::text NOT NULL,
    registration_contact_email text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_institution_status CHECK ((status = ANY (ARRAY['PROSPECT'::text, 'ONBOARDING'::text, 'ACTIVE'::text, 'SUSPENDED'::text, 'DECLINED'::text, 'WITHDRAWN'::text]))),
    CONSTRAINT ck_institution_type CHECK ((institution_type = ANY (ARRAY['NATIONAL_BANK'::text, 'STATE_MEMBER_BANK'::text, 'STATE_NONMEMBER_BANK'::text, 'SAVINGS_INSTITUTION'::text, 'CREDIT_UNION'::text, 'TRUST_COMPANY'::text, 'OTHER'::text])))
);

ALTER TABLE ONLY hazel.institution FORCE ROW LEVEL SECURITY;


--
-- Name: COLUMN institution.rssd_id; Type: COMMENT; Schema: hazel; Owner: -
--

COMMENT ON COLUMN hazel.institution.rssd_id IS 'Maintained copy of hazel.rafa.rssd_id. Written only by fn_propagate_rafa; hop_app has no UPDATE privilege on this column.';


--
-- Name: onboarding_case; Type: TABLE; Schema: hazel; Owner: -
--

CREATE TABLE hazel.onboarding_case (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    institution_id uuid NOT NULL,
    case_number text NOT NULL,
    current_stage text DEFAULT 'INQUIRY'::text NOT NULL,
    current_status text DEFAULT 'IN_PROGRESS'::text NOT NULL,
    decision_status text DEFAULT 'PENDING'::text NOT NULL,
    coverbase_session_id text,
    coverbase_vendor_id text,
    coverbase_questionnaire_id text,
    coverbase_session_status text DEFAULT 'NOT_CREATED'::text NOT NULL,
    coverbase_assessment_status text DEFAULT 'NOT_STARTED'::text NOT NULL,
    coverbase_sync_status text DEFAULT 'PENDING'::text NOT NULL,
    inherent_risk_score numeric(5,2),
    rafa_score integer,
    assessment_outcome text,
    coverbase_last_synced_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_case_completed_after_created CHECK (((completed_at IS NULL) OR (completed_at >= created_at))),
    CONSTRAINT ck_case_decision CHECK ((decision_status = ANY (ARRAY['PENDING'::text, 'APPROVED'::text, 'DECLINED'::text, 'MORE_INFO_REQUIRED'::text]))),
    CONSTRAINT ck_case_outcome CHECK (((assessment_outcome IS NULL) OR (assessment_outcome = ANY (ARRAY['LOW'::text, 'MODERATE'::text, 'HIGH'::text, 'CRITICAL'::text])))),
    CONSTRAINT ck_case_scores CHECK ((((inherent_risk_score IS NULL) OR (inherent_risk_score >= (0)::numeric)) AND ((rafa_score IS NULL) OR ((rafa_score)::numeric >= (0)::numeric)))),
    CONSTRAINT ck_case_stage CHECK ((current_stage = ANY (ARRAY['INQUIRY'::text, 'ELIGIBILITY_SCREENING'::text, 'NDA'::text, 'RISK_ASSESSMENT'::text, 'VANTAGE_REVIEW'::text, 'ACCOUNT_OPENING'::text, 'COMPLETED'::text]))),
    CONSTRAINT ck_case_status CHECK ((current_status = ANY (ARRAY['IN_PROGRESS'::text, 'AWAITING_MEMBER'::text, 'AWAITING_VANTAGE'::text, 'ON_HOLD'::text, 'COMPLETED'::text, 'DECLINED'::text]))),
    CONSTRAINT ck_cb_assessment_status CHECK ((coverbase_assessment_status = ANY (ARRAY['NOT_STARTED'::text, 'PENDING'::text, 'IN_REVIEW'::text, 'COMPLETED'::text, 'FAILED'::text]))),
    CONSTRAINT ck_cb_session_status CHECK ((coverbase_session_status = ANY (ARRAY['NOT_CREATED'::text, 'CREATED'::text, 'IN_PROGRESS'::text, 'SUBMITTED'::text, 'EXPIRED'::text, 'CANCELLED'::text]))),
    CONSTRAINT ck_cb_sync_status CHECK ((coverbase_sync_status = ANY (ARRAY['PENDING'::text, 'IN_PROGRESS'::text, 'SYNCED'::text, 'FAILED'::text, 'RETRYING'::text, 'NOT_APPLICABLE'::text])))
);

ALTER TABLE ONLY hazel.onboarding_case FORCE ROW LEVEL SECURITY;


--
-- Name: COLUMN onboarding_case.rafa_score; Type: COMMENT; Schema: hazel; Owner: -
--

COMMENT ON COLUMN hazel.onboarding_case.rafa_score IS 'Maintained copy of hazel.rafa.rafa_score. Written only by fn_propagate_rafa; hop_app has no UPDATE privilege on this column.';


--
-- Name: rafa; Type: TABLE; Schema: hazel; Owner: -
--

CREATE TABLE hazel.rafa (
    institution_id uuid NOT NULL,
    fdic_certificate text,
    rssd_id text,
    rafa_score numeric(5,2),
    rafa_status text DEFAULT 'NOT_SCREENED'::text NOT NULL,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_rafa_score CHECK (((rafa_score IS NULL) OR (rafa_score >= (0)::numeric))),
    CONSTRAINT ck_rafa_status CHECK ((rafa_status = ANY (ARRAY['NOT_SCREENED'::text, 'PENDING'::text, 'PASS'::text, 'PROOF_REQUIRED'::text, 'DECLINE'::text, 'ERROR'::text])))
);

ALTER TABLE ONLY hazel.rafa FORCE ROW LEVEL SECURITY;


--
-- Name: TABLE rafa; Type: COMMENT; Schema: hazel; Owner: -
--

COMMENT ON TABLE hazel.rafa IS 'Projection of the RAFA platform result. fetched_at records when it was pulled, so staleness is visible.';


--
-- Name: user; Type: TABLE; Schema: hazel; Owner: -
--

CREATE TABLE hazel."user" (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    institution_id uuid,
    external_identity_id text NOT NULL,
    email text NOT NULL,
    first_name text,
    last_name text,
    role text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_user_role CHECK ((role = ANY (ARRAY['MEMBER_ADMIN'::text, 'MEMBER_CONTRIBUTOR'::text, 'MEMBER_VIEWER'::text, 'INTERNAL_REVIEWER'::text, 'INTERNAL_RISK'::text, 'INTERNAL_APPROVER'::text, 'INTERNAL_ADMIN'::text, 'INTERNAL_SUPPORT'::text]))),
    CONSTRAINT ck_user_scope CHECK (((starts_with(role, 'INTERNAL_'::text) AND (institution_id IS NULL)) OR (starts_with(role, 'MEMBER_'::text) AND (institution_id IS NOT NULL))))
);

ALTER TABLE ONLY hazel."user" FORCE ROW LEVEL SECURITY;


--
-- Name: user app_user_pkey; Type: CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel."user"
    ADD CONSTRAINT app_user_pkey PRIMARY KEY (id);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: case_stage_transition case_stage_transition_pkey; Type: CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.case_stage_transition
    ADD CONSTRAINT case_stage_transition_pkey PRIMARY KEY (id);


--
-- Name: document document_pkey; Type: CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.document
    ADD CONSTRAINT document_pkey PRIMARY KEY (id);


--
-- Name: institution institution_pkey; Type: CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.institution
    ADD CONSTRAINT institution_pkey PRIMARY KEY (id);


--
-- Name: onboarding_case onboarding_case_pkey; Type: CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.onboarding_case
    ADD CONSTRAINT onboarding_case_pkey PRIMARY KEY (id);


--
-- Name: rafa rafa_pkey; Type: CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.rafa
    ADD CONSTRAINT rafa_pkey PRIMARY KEY (institution_id);


--
-- Name: onboarding_case uq_case_id_institution; Type: CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.onboarding_case
    ADD CONSTRAINT uq_case_id_institution UNIQUE (id, institution_id);


--
-- Name: onboarding_case uq_case_number; Type: CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.onboarding_case
    ADD CONSTRAINT uq_case_number UNIQUE (case_number);


--
-- Name: user uq_user_email; Type: CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel."user"
    ADD CONSTRAINT uq_user_email UNIQUE (email);


--
-- Name: user uq_user_external_identity; Type: CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel."user"
    ADD CONSTRAINT uq_user_external_identity UNIQUE (external_identity_id);


--
-- Name: ix_audit_actor; Type: INDEX; Schema: hazel; Owner: -
--

CREATE INDEX ix_audit_actor ON hazel.audit_log USING btree (changed_by);


--
-- Name: ix_audit_entity; Type: INDEX; Schema: hazel; Owner: -
--

CREATE INDEX ix_audit_entity ON hazel.audit_log USING btree (entity_type, entity_id, occurred_at DESC);


--
-- Name: ix_audit_institution; Type: INDEX; Schema: hazel; Owner: -
--

CREATE INDEX ix_audit_institution ON hazel.audit_log USING btree (institution_id, occurred_at DESC);


--
-- Name: ix_case_institution; Type: INDEX; Schema: hazel; Owner: -
--

CREATE INDEX ix_case_institution ON hazel.onboarding_case USING btree (institution_id);


--
-- Name: ix_case_stage_status; Type: INDEX; Schema: hazel; Owner: -
--

CREATE INDEX ix_case_stage_status ON hazel.onboarding_case USING btree (current_stage, current_status);


--
-- Name: ix_document_case; Type: INDEX; Schema: hazel; Owner: -
--

CREATE INDEX ix_document_case ON hazel.document USING btree (onboarding_case_id);


--
-- Name: ix_document_institution; Type: INDEX; Schema: hazel; Owner: -
--

CREATE INDEX ix_document_institution ON hazel.document USING btree (institution_id);


--
-- Name: ix_document_type; Type: INDEX; Schema: hazel; Owner: -
--

CREATE INDEX ix_document_type ON hazel.document USING btree (document_type_name);


--
-- Name: ix_document_uploader; Type: INDEX; Schema: hazel; Owner: -
--

CREATE INDEX ix_document_uploader ON hazel.document USING btree (uploaded_by);


--
-- Name: ix_transition_actor; Type: INDEX; Schema: hazel; Owner: -
--

CREATE INDEX ix_transition_actor ON hazel.case_stage_transition USING btree (changed_by);


--
-- Name: ix_transition_case; Type: INDEX; Schema: hazel; Owner: -
--

CREATE INDEX ix_transition_case ON hazel.case_stage_transition USING btree (onboarding_case_id, occurred_at DESC);


--
-- Name: ix_transition_inst; Type: INDEX; Schema: hazel; Owner: -
--

CREATE INDEX ix_transition_inst ON hazel.case_stage_transition USING btree (institution_id);


--
-- Name: ix_user_institution; Type: INDEX; Schema: hazel; Owner: -
--

CREATE INDEX ix_user_institution ON hazel."user" USING btree (institution_id);


--
-- Name: ux_case_one_active; Type: INDEX; Schema: hazel; Owner: -
--

CREATE UNIQUE INDEX ux_case_one_active ON hazel.onboarding_case USING btree (institution_id) WHERE (current_status <> ALL (ARRAY['COMPLETED'::text, 'WITHDRAWN'::text, 'DECLINED'::text]));


--
-- Name: ux_institution_fdic; Type: INDEX; Schema: hazel; Owner: -
--

CREATE UNIQUE INDEX ux_institution_fdic ON hazel.institution USING btree (fdic_certificate) WHERE (fdic_certificate IS NOT NULL);


--
-- Name: document trg_audit; Type: TRIGGER; Schema: hazel; Owner: -
--

CREATE TRIGGER trg_audit AFTER INSERT OR DELETE OR UPDATE ON hazel.document FOR EACH ROW EXECUTE FUNCTION hazel.fn_audit();


--
-- Name: institution trg_audit; Type: TRIGGER; Schema: hazel; Owner: -
--

CREATE TRIGGER trg_audit AFTER INSERT OR DELETE OR UPDATE ON hazel.institution FOR EACH ROW EXECUTE FUNCTION hazel.fn_audit();


--
-- Name: onboarding_case trg_audit; Type: TRIGGER; Schema: hazel; Owner: -
--

CREATE TRIGGER trg_audit AFTER INSERT OR DELETE OR UPDATE ON hazel.onboarding_case FOR EACH ROW EXECUTE FUNCTION hazel.fn_audit();


--
-- Name: rafa trg_audit; Type: TRIGGER; Schema: hazel; Owner: -
--

CREATE TRIGGER trg_audit AFTER INSERT OR DELETE OR UPDATE ON hazel.rafa FOR EACH ROW EXECUTE FUNCTION hazel.fn_audit();


--
-- Name: user trg_audit; Type: TRIGGER; Schema: hazel; Owner: -
--

CREATE TRIGGER trg_audit AFTER INSERT OR DELETE OR UPDATE ON hazel."user" FOR EACH ROW EXECUTE FUNCTION hazel.fn_audit();


--
-- Name: rafa trg_propagate; Type: TRIGGER; Schema: hazel; Owner: -
--

CREATE TRIGGER trg_propagate AFTER INSERT OR UPDATE ON hazel.rafa FOR EACH ROW EXECUTE FUNCTION hazel.fn_propagate_rafa();


--
-- Name: onboarding_case trg_stage_history; Type: TRIGGER; Schema: hazel; Owner: -
--

CREATE TRIGGER trg_stage_history AFTER INSERT OR UPDATE ON hazel.onboarding_case FOR EACH ROW EXECUTE FUNCTION hazel.fn_log_stage_transition();


--
-- Name: document trg_touch; Type: TRIGGER; Schema: hazel; Owner: -
--

CREATE TRIGGER trg_touch BEFORE UPDATE ON hazel.document FOR EACH ROW EXECUTE FUNCTION hazel.fn_touch_updated_at();


--
-- Name: institution trg_touch; Type: TRIGGER; Schema: hazel; Owner: -
--

CREATE TRIGGER trg_touch BEFORE UPDATE ON hazel.institution FOR EACH ROW EXECUTE FUNCTION hazel.fn_touch_updated_at();


--
-- Name: onboarding_case trg_touch; Type: TRIGGER; Schema: hazel; Owner: -
--

CREATE TRIGGER trg_touch BEFORE UPDATE ON hazel.onboarding_case FOR EACH ROW EXECUTE FUNCTION hazel.fn_touch_updated_at();


--
-- Name: rafa trg_touch; Type: TRIGGER; Schema: hazel; Owner: -
--

CREATE TRIGGER trg_touch BEFORE UPDATE ON hazel.rafa FOR EACH ROW EXECUTE FUNCTION hazel.fn_touch_updated_at();


--
-- Name: user trg_touch; Type: TRIGGER; Schema: hazel; Owner: -
--

CREATE TRIGGER trg_touch BEFORE UPDATE ON hazel."user" FOR EACH ROW EXECUTE FUNCTION hazel.fn_touch_updated_at();


--
-- Name: document trg_uploader; Type: TRIGGER; Schema: hazel; Owner: -
--

CREATE TRIGGER trg_uploader BEFORE INSERT OR UPDATE ON hazel.document FOR EACH ROW EXECUTE FUNCTION hazel.fn_check_uploader();


--
-- Name: user app_user_institution_id_fkey; Type: FK CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel."user"
    ADD CONSTRAINT app_user_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES hazel.institution(id) ON DELETE RESTRICT;


--
-- Name: audit_log audit_log_changed_by_fkey; Type: FK CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.audit_log
    ADD CONSTRAINT audit_log_changed_by_fkey FOREIGN KEY (changed_by) REFERENCES hazel."user"(id) ON DELETE RESTRICT;


--
-- Name: audit_log audit_log_institution_id_fkey; Type: FK CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.audit_log
    ADD CONSTRAINT audit_log_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES hazel.institution(id) ON DELETE RESTRICT;


--
-- Name: case_stage_transition case_stage_transition_changed_by_fkey; Type: FK CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.case_stage_transition
    ADD CONSTRAINT case_stage_transition_changed_by_fkey FOREIGN KEY (changed_by) REFERENCES hazel."user"(id) ON DELETE RESTRICT;


--
-- Name: document document_uploaded_by_fkey; Type: FK CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.document
    ADD CONSTRAINT document_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES hazel."user"(id) ON DELETE RESTRICT;


--
-- Name: document fk_document_case; Type: FK CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.document
    ADD CONSTRAINT fk_document_case FOREIGN KEY (onboarding_case_id, institution_id) REFERENCES hazel.onboarding_case(id, institution_id) ON DELETE RESTRICT;


--
-- Name: case_stage_transition fk_transition_case; Type: FK CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.case_stage_transition
    ADD CONSTRAINT fk_transition_case FOREIGN KEY (onboarding_case_id, institution_id) REFERENCES hazel.onboarding_case(id, institution_id) ON DELETE RESTRICT;


--
-- Name: onboarding_case onboarding_case_institution_id_fkey; Type: FK CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.onboarding_case
    ADD CONSTRAINT onboarding_case_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES hazel.institution(id) ON DELETE RESTRICT;


--
-- Name: rafa rafa_institution_id_fkey; Type: FK CONSTRAINT; Schema: hazel; Owner: -
--

ALTER TABLE ONLY hazel.rafa
    ADD CONSTRAINT rafa_institution_id_fkey FOREIGN KEY (institution_id) REFERENCES hazel.institution(id) ON DELETE CASCADE;


--
-- Name: audit_log; Type: ROW SECURITY; Schema: hazel; Owner: -
--

ALTER TABLE hazel.audit_log ENABLE ROW LEVEL SECURITY;

--
-- Name: case_stage_transition; Type: ROW SECURITY; Schema: hazel; Owner: -
--

ALTER TABLE hazel.case_stage_transition ENABLE ROW LEVEL SECURITY;

--
-- Name: document; Type: ROW SECURITY; Schema: hazel; Owner: -
--

ALTER TABLE hazel.document ENABLE ROW LEVEL SECURITY;

--
-- Name: institution; Type: ROW SECURITY; Schema: hazel; Owner: -
--

ALTER TABLE hazel.institution ENABLE ROW LEVEL SECURITY;

--
-- Name: onboarding_case; Type: ROW SECURITY; Schema: hazel; Owner: -
--

ALTER TABLE hazel.onboarding_case ENABLE ROW LEVEL SECURITY;

--
-- Name: institution p_intake; Type: POLICY; Schema: hazel; Owner: -
--

CREATE POLICY p_intake ON hazel.institution FOR INSERT WITH CHECK (hazel.is_system());


--
-- Name: onboarding_case p_intake; Type: POLICY; Schema: hazel; Owner: -
--

CREATE POLICY p_intake ON hazel.onboarding_case FOR INSERT WITH CHECK (hazel.is_system());


--
-- Name: user p_intake; Type: POLICY; Schema: hazel; Owner: -
--

CREATE POLICY p_intake ON hazel."user" FOR INSERT WITH CHECK (hazel.is_system());


--
-- Name: audit_log p_tenant; Type: POLICY; Schema: hazel; Owner: -
--

CREATE POLICY p_tenant ON hazel.audit_log USING ((hazel.is_internal() OR (institution_id = hazel.current_institution()))) WITH CHECK ((hazel.is_internal() OR (institution_id = hazel.current_institution()) OR hazel.is_system()));


--
-- Name: case_stage_transition p_tenant; Type: POLICY; Schema: hazel; Owner: -
--

CREATE POLICY p_tenant ON hazel.case_stage_transition USING ((hazel.is_internal() OR (institution_id = hazel.current_institution()))) WITH CHECK ((hazel.is_internal() OR (institution_id = hazel.current_institution()) OR hazel.is_system()));


--
-- Name: document p_tenant; Type: POLICY; Schema: hazel; Owner: -
--

CREATE POLICY p_tenant ON hazel.document USING ((hazel.is_internal() OR (institution_id = hazel.current_institution()))) WITH CHECK ((hazel.is_internal() OR (institution_id = hazel.current_institution())));


--
-- Name: institution p_tenant; Type: POLICY; Schema: hazel; Owner: -
--

CREATE POLICY p_tenant ON hazel.institution USING ((hazel.is_internal() OR (id = hazel.current_institution()))) WITH CHECK ((hazel.is_internal() OR (id = hazel.current_institution())));


--
-- Name: onboarding_case p_tenant; Type: POLICY; Schema: hazel; Owner: -
--

CREATE POLICY p_tenant ON hazel.onboarding_case USING ((hazel.is_internal() OR (institution_id = hazel.current_institution()))) WITH CHECK ((hazel.is_internal() OR (institution_id = hazel.current_institution())));


--
-- Name: rafa p_tenant; Type: POLICY; Schema: hazel; Owner: -
--

CREATE POLICY p_tenant ON hazel.rafa USING ((hazel.is_internal() OR (institution_id = hazel.current_institution()))) WITH CHECK ((hazel.is_internal() OR (institution_id = hazel.current_institution())));


--
-- Name: user p_tenant; Type: POLICY; Schema: hazel; Owner: -
--

CREATE POLICY p_tenant ON hazel."user" USING ((hazel.is_internal() OR (institution_id = hazel.current_institution()))) WITH CHECK ((hazel.is_internal() OR (institution_id = hazel.current_institution())));


--
-- Name: rafa; Type: ROW SECURITY; Schema: hazel; Owner: -
--

ALTER TABLE hazel.rafa ENABLE ROW LEVEL SECURITY;

--
-- Name: user; Type: ROW SECURITY; Schema: hazel; Owner: -
--

ALTER TABLE hazel."user" ENABLE ROW LEVEL SECURITY;

--
-- Name: SCHEMA hazel; Type: ACL; Schema: -; Owner: -
--

GRANT USAGE ON SCHEMA hazel TO databricks_gateway;
GRANT ALL ON SCHEMA hazel TO databricks_superuser WITH GRANT OPTION;
GRANT USAGE ON SCHEMA hazel TO databricks_reader_16405;
GRANT ALL ON SCHEMA hazel TO databricks_writer_16405;
GRANT USAGE ON SCHEMA hazel TO hop_app;


--
-- Name: FUNCTION current_institution(); Type: ACL; Schema: hazel; Owner: -
--

GRANT ALL ON FUNCTION hazel.current_institution() TO hop_app;


--
-- Name: FUNCTION current_user_id(); Type: ACL; Schema: hazel; Owner: -
--

GRANT ALL ON FUNCTION hazel.current_user_id() TO hop_app;


--
-- Name: FUNCTION fn_audit(); Type: ACL; Schema: hazel; Owner: -
--

GRANT ALL ON FUNCTION hazel.fn_audit() TO hop_app;


--
-- Name: FUNCTION fn_check_uploader(); Type: ACL; Schema: hazel; Owner: -
--

GRANT ALL ON FUNCTION hazel.fn_check_uploader() TO hop_app;


--
-- Name: FUNCTION fn_log_stage_transition(); Type: ACL; Schema: hazel; Owner: -
--

GRANT ALL ON FUNCTION hazel.fn_log_stage_transition() TO hop_app;


--
-- Name: FUNCTION fn_propagate_rafa(); Type: ACL; Schema: hazel; Owner: -
--

GRANT ALL ON FUNCTION hazel.fn_propagate_rafa() TO hop_app;


--
-- Name: FUNCTION fn_touch_updated_at(); Type: ACL; Schema: hazel; Owner: -
--

GRANT ALL ON FUNCTION hazel.fn_touch_updated_at() TO hop_app;


--
-- Name: FUNCTION is_internal(); Type: ACL; Schema: hazel; Owner: -
--

GRANT ALL ON FUNCTION hazel.is_internal() TO hop_app;


--
-- Name: FUNCTION is_system(); Type: ACL; Schema: hazel; Owner: -
--

GRANT ALL ON FUNCTION hazel.is_system() TO hop_app;


--
-- Name: TABLE audit_log; Type: ACL; Schema: hazel; Owner: -
--

GRANT SELECT ON TABLE hazel.audit_log TO databricks_gateway;
GRANT ALL ON TABLE hazel.audit_log TO databricks_superuser WITH GRANT OPTION;
GRANT SELECT ON TABLE hazel.audit_log TO databricks_reader_16405;
GRANT SELECT,INSERT ON TABLE hazel.audit_log TO hop_app;


--
-- Name: TABLE case_stage_transition; Type: ACL; Schema: hazel; Owner: -
--

GRANT SELECT ON TABLE hazel.case_stage_transition TO databricks_gateway;
GRANT ALL ON TABLE hazel.case_stage_transition TO databricks_superuser WITH GRANT OPTION;
GRANT SELECT ON TABLE hazel.case_stage_transition TO databricks_reader_16405;
GRANT SELECT,INSERT ON TABLE hazel.case_stage_transition TO hop_app;


--
-- Name: TABLE document; Type: ACL; Schema: hazel; Owner: -
--

GRANT SELECT ON TABLE hazel.document TO databricks_gateway;
GRANT ALL ON TABLE hazel.document TO databricks_superuser WITH GRANT OPTION;
GRANT SELECT ON TABLE hazel.document TO databricks_reader_16405;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE hazel.document TO hop_app;


--
-- Name: TABLE institution; Type: ACL; Schema: hazel; Owner: -
--

GRANT SELECT ON TABLE hazel.institution TO databricks_gateway;
GRANT ALL ON TABLE hazel.institution TO databricks_superuser WITH GRANT OPTION;
GRANT SELECT ON TABLE hazel.institution TO databricks_reader_16405;
GRANT SELECT,INSERT,DELETE ON TABLE hazel.institution TO hop_app;


--
-- Name: COLUMN institution.legal_name; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(legal_name) ON TABLE hazel.institution TO hop_app;


--
-- Name: COLUMN institution.fdic_certificate; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(fdic_certificate) ON TABLE hazel.institution TO hop_app;


--
-- Name: COLUMN institution.institution_type; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(institution_type) ON TABLE hazel.institution TO hop_app;


--
-- Name: COLUMN institution.status; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(status) ON TABLE hazel.institution TO hop_app;


--
-- Name: COLUMN institution.registration_contact_email; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(registration_contact_email) ON TABLE hazel.institution TO hop_app;


--
-- Name: COLUMN institution.updated_at; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(updated_at) ON TABLE hazel.institution TO hop_app;


--
-- Name: TABLE onboarding_case; Type: ACL; Schema: hazel; Owner: -
--

GRANT SELECT ON TABLE hazel.onboarding_case TO databricks_gateway;
GRANT ALL ON TABLE hazel.onboarding_case TO databricks_superuser WITH GRANT OPTION;
GRANT SELECT ON TABLE hazel.onboarding_case TO databricks_reader_16405;
GRANT SELECT,INSERT,DELETE ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: COLUMN onboarding_case.case_number; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(case_number) ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: COLUMN onboarding_case.current_stage; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(current_stage) ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: COLUMN onboarding_case.current_status; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(current_status) ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: COLUMN onboarding_case.decision_status; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(decision_status) ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: COLUMN onboarding_case.coverbase_session_id; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(coverbase_session_id) ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: COLUMN onboarding_case.coverbase_vendor_id; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(coverbase_vendor_id) ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: COLUMN onboarding_case.coverbase_questionnaire_id; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(coverbase_questionnaire_id) ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: COLUMN onboarding_case.coverbase_session_status; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(coverbase_session_status) ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: COLUMN onboarding_case.coverbase_assessment_status; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(coverbase_assessment_status) ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: COLUMN onboarding_case.coverbase_sync_status; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(coverbase_sync_status) ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: COLUMN onboarding_case.inherent_risk_score; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(inherent_risk_score) ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: COLUMN onboarding_case.assessment_outcome; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(assessment_outcome) ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: COLUMN onboarding_case.coverbase_last_synced_at; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(coverbase_last_synced_at) ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: COLUMN onboarding_case.completed_at; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(completed_at) ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: COLUMN onboarding_case.updated_at; Type: ACL; Schema: hazel; Owner: -
--

GRANT UPDATE(updated_at) ON TABLE hazel.onboarding_case TO hop_app;


--
-- Name: TABLE rafa; Type: ACL; Schema: hazel; Owner: -
--

GRANT SELECT ON TABLE hazel.rafa TO databricks_gateway;
GRANT ALL ON TABLE hazel.rafa TO databricks_superuser WITH GRANT OPTION;
GRANT SELECT ON TABLE hazel.rafa TO databricks_reader_16405;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE hazel.rafa TO hop_app;


--
-- Name: TABLE "user"; Type: ACL; Schema: hazel; Owner: -
--

GRANT SELECT ON TABLE hazel."user" TO databricks_gateway;
GRANT ALL ON TABLE hazel."user" TO databricks_superuser WITH GRANT OPTION;
GRANT SELECT ON TABLE hazel."user" TO databricks_reader_16405;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE hazel."user" TO hop_app;


--
-- PostgreSQL database dump complete
--

\unrestrict wF1Qs5HhTdmU8xcfTb3xstDsxPK9QJ4r8X1om8mntTQvkNajrgCETVSZFQmtMfV

