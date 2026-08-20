-- 001_schema.sql — Hazel HOP schema, ported from the inline SQLite DDL that used to
-- live in backend/app/db.py:46-135 and re-run on every boot.
--
-- Target: Postgres 17, database `databricks_postgres`, schema `hazel`.
-- The database itself is NOT created here; it is the injected PGDATABASE and is
-- owned by our Databricks identity.

CREATE SCHEMA IF NOT EXISTS hazel;

SET search_path = hazel, public;


-- ---------------------------------------------------------------------------
-- Tenancy root
-- ---------------------------------------------------------------------------

CREATE TABLE hazel.organizations (
    id          uuid        PRIMARY KEY,
    slug        text        NOT NULL UNIQUE,
    name        text        NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Every tenant-scoped table below carries this column definition verbatim.
--
--     org_id uuid NOT NULL
--         DEFAULT nullif(current_setting('app.org_id', true), '')::uuid
--         REFERENCES hazel.organizations(id)
--
-- The DEFAULT is deliberately the same expression the RLS policy checks in
-- 002_rls.sql. Two consequences worth stating out loud:
--
--   1. No INSERT anywhere in the application names org_id, and none can write a
--      value that disagrees with the policy — the checked value and the stored
--      value come from one source.
--   2. nullif(...) is required, not cosmetic. current_setting(...,true) returns
--      NULL when the GUC was never set, but returns '' when it was set to the
--      empty string, and ''::uuid raises 22P02. NULL then trips NOT NULL and the
--      write fails closed, which is the intent.


-- ---------------------------------------------------------------------------
-- onboarding_cases — the root aggregate (was db.py:50-67)
-- ---------------------------------------------------------------------------

CREATE TABLE hazel.onboarding_cases (
    id                                text        PRIMARY KEY,
    org_id                            uuid        NOT NULL
        DEFAULT nullif(current_setting('app.org_id', true), '')::uuid
        REFERENCES hazel.organizations(id),
    institution_id                    text        NOT NULL,
    current_stage                     text        NOT NULL,
    nda_accepted_at                   timestamptz,
    institution_profile_completed_at  timestamptz,
    documents_completed_at            timestamptz,
    due_diligence_completed_at        timestamptz,
    risk_questions_submitted_at       timestamptz,
    coverbase_session_id              text,
    coverbase_vendor_id               text,
    coverbase_status                  text,
    hazel_review_status               text,
    review_status                     text        NOT NULL DEFAULT 'Not started',
    additional_information_required   boolean     NOT NULL DEFAULT false,
    created_at                        timestamptz NOT NULL,
    updated_at                        timestamptz NOT NULL,

    -- The stage enum has lived only in Python (db.py:14-22) with no database
    -- enforcement. Keep STAGES as the single source of truth and regenerate this
    -- constraint from it rather than editing the list in two places.
    CONSTRAINT onboarding_cases_current_stage_check CHECK (current_stage IN (
        'NDA_PENDING',
        'NDA_ACCEPTED',
        'INSTITUTION_PROFILE',
        'DOCUMENTS',
        'DUE_DILIGENCE',
        'RISK_QUESTIONS',
        'HAZEL_REVIEW'
    )),

    -- Target for the composite foreign keys on the child tables below. Without
    -- this, a child row in org B could reference a case in org A: foreign key
    -- validation runs as the table owner and is not subject to RLS.
    CONSTRAINT onboarding_cases_org_id_key UNIQUE (org_id, id)
);


-- ---------------------------------------------------------------------------
-- institution_profiles (was db.py:68-78)
-- ---------------------------------------------------------------------------

CREATE TABLE hazel.institution_profiles (
    case_id                                     text        PRIMARY KEY,
    org_id                                      uuid        NOT NULL
        DEFAULT nullif(current_setting('app.org_id', true), '')::uuid
        REFERENCES hazel.organizations(id),
    legal_name                                  text,
    fdic_certificate_number                     text,
    rssd_id                                     text,
    institution_type                            text,
    website                                     text,
    headquarters                                text,
    admission_type                              text,
    international_correspondent_relationships   text,
    has_dba                                     text,
    has_fintech_or_baas_programs                text,
    primary_contact_name                        text,
    primary_contact_title                       text,
    primary_contact_email                       text,
    additional_responses_json                   jsonb       NOT NULL DEFAULT '{}'::jsonb,
    updated_at                                  timestamptz NOT NULL,

    FOREIGN KEY (org_id, case_id)
        REFERENCES hazel.onboarding_cases (org_id, id) ON DELETE CASCADE
);


-- ---------------------------------------------------------------------------
-- express_interest_submissions (was db.py:79-85)
-- ---------------------------------------------------------------------------

CREATE TABLE hazel.express_interest_submissions (
    case_id                  text        PRIMARY KEY,
    org_id                   uuid        NOT NULL
        DEFAULT nullif(current_setting('app.org_id', true), '')::uuid
        REFERENCES hazel.organizations(id),
    legal_name               text,
    fdic_certificate_number  text,
    rssd_id                  text,
    institution_type         text,
    website                  text,
    headquarters             text,
    contact_name             text,
    contact_title            text,
    contact_email            text,
    data_json                jsonb       NOT NULL DEFAULT '{}'::jsonb,
    updated_at               timestamptz NOT NULL,

    FOREIGN KEY (org_id, case_id)
        REFERENCES hazel.onboarding_cases (org_id, id) ON DELETE CASCADE
);


-- ---------------------------------------------------------------------------
-- documents (was db.py:86-98, including the six columns db.py:155-165 used to
-- bolt on at runtime with PRAGMA-then-ALTER)
-- ---------------------------------------------------------------------------

CREATE TABLE hazel.documents (
    id                            bigint      GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    org_id                        uuid        NOT NULL
        DEFAULT nullif(current_setting('app.org_id', true), '')::uuid
        REFERENCES hazel.organizations(id),
    case_id                       text        NOT NULL,
    document_type                 text        NOT NULL,
    original_name                 text        NOT NULL,
    stored_name                   text        NOT NULL,
    size_bytes                    bigint      NOT NULL,
    created_at                    timestamptz NOT NULL,
    coverbase_document_id         text,
    coverbase_sync_status         text        NOT NULL DEFAULT 'not_started',
    coverbase_synced_at           timestamptz,
    coverbase_sync_error          text,
    coverbase_sync_details_json   jsonb       NOT NULL DEFAULT '{}'::jsonb,
    file_sha256                   text,

    FOREIGN KEY (org_id, case_id)
        REFERENCES hazel.onboarding_cases (org_id, id) ON DELETE CASCADE,

    -- Target for review_clarifications' two document references. See the note there.
    CONSTRAINT documents_org_id_key UNIQUE (org_id, id)
);


-- ---------------------------------------------------------------------------
-- due_diligence (was db.py:99-102)
-- ---------------------------------------------------------------------------

CREATE TABLE hazel.due_diligence (
    case_id     text        PRIMARY KEY,
    org_id      uuid        NOT NULL
        DEFAULT nullif(current_setting('app.org_id', true), '')::uuid
        REFERENCES hazel.organizations(id),
    data_json   jsonb       NOT NULL DEFAULT '{}'::jsonb,
    updated_at  timestamptz NOT NULL,

    FOREIGN KEY (org_id, case_id)
        REFERENCES hazel.onboarding_cases (org_id, id) ON DELETE CASCADE
);


-- ---------------------------------------------------------------------------
-- review_clarifications (was db.py:109-131)
-- ---------------------------------------------------------------------------

CREATE TABLE hazel.review_clarifications (
    id                                text        PRIMARY KEY,
    org_id                            uuid        NOT NULL
        DEFAULT nullif(current_setting('app.org_id', true), '')::uuid
        REFERENCES hazel.organizations(id),
    case_id                           text        NOT NULL,
    source                            text        NOT NULL,
    source_reference_id               text,
    requested_by                      text        NOT NULL,
    request_text                      text        NOT NULL,
    request_type                      text        NOT NULL DEFAULT 'additional_information',
    question_id                       text,
    requested_at                      timestamptz NOT NULL,
    due_at                            timestamptz,
    status                            text        NOT NULL,
    member_response                   text        NOT NULL DEFAULT '',
    submitted_at                      timestamptz,
    document_required                 boolean     NOT NULL DEFAULT false,
    document_label                    text,

    -- Single-column references on purpose. A composite (org_id, doc_id) key would
    -- be stricter, but ON DELETE SET NULL nulls *every* column in the constraint,
    -- which would drive org_id to NULL and violate its NOT NULL. Cross-org
    -- integrity for these two is carried by the composite case_id key below:
    -- a clarification cannot belong to another org's case in the first place.
    replacement_of_hazel_document_id  bigint REFERENCES hazel.documents(id) ON DELETE SET NULL,
    uploaded_hazel_document_id        bigint REFERENCES hazel.documents(id) ON DELETE SET NULL,

    coverbase_sync_status             text        NOT NULL DEFAULT 'not_started',
    created_at                        timestamptz NOT NULL,
    updated_at                        timestamptz NOT NULL,

    CONSTRAINT review_clarifications_status_check
        CHECK (status IN ('open', 'draft', 'submitted', 'resolved')),

    FOREIGN KEY (org_id, case_id)
        REFERENCES hazel.onboarding_cases (org_id, id) ON DELETE CASCADE
);


-- ---------------------------------------------------------------------------
-- case_decisions — new, append-only
-- ---------------------------------------------------------------------------
--
-- Written by update_stage() in the same transaction as the stage UPDATE. It has
-- no ON DELETE CASCADE to onboarding_cases: a decision record that disappears
-- with the thing it decided about is not a record. The reference is therefore
-- deliberately absent rather than RESTRICT — deleting a case is allowed, and its
-- decisions outlive it.

CREATE TABLE hazel.case_decisions (
    id          bigint      GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    org_id      uuid        NOT NULL
        DEFAULT nullif(current_setting('app.org_id', true), '')::uuid
        REFERENCES hazel.organizations(id),
    case_id     text        NOT NULL,
    decided_at  timestamptz NOT NULL DEFAULT now(),
    decided_by  text        NOT NULL,
    decision    text        NOT NULL,
    from_stage  text,
    to_stage    text,
    rationale   text,
    payload     jsonb       NOT NULL DEFAULT '{}'::jsonb
);


-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

CREATE INDEX idx_onboarding_cases_org
    ON hazel.onboarding_cases (org_id);

CREATE INDEX idx_documents_case
    ON hazel.documents (case_id, created_at DESC);

CREATE INDEX idx_review_clarifications_case
    ON hazel.review_clarifications (case_id, requested_at DESC);

CREATE INDEX idx_case_decisions_case
    ON hazel.case_decisions (case_id, decided_at DESC);
