import logging
import os
import re
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from psycopg.types.json import Jsonb

from app.db import connection, require_case, utc_now
from app.models import clarification_payload
from app.schemas import DevCaseCreate, DevClarificationCreate
from app.storage import storage

router = APIRouter(prefix="/api/dev", tags=["local-development"])
logger = logging.getLogger("uvicorn.error")
SYNTHETIC_CASE_PATTERN = re.compile(r"^HAZEL-TEST-[A-Za-z0-9_-]+$")
DEV_MODE_ENABLED = os.getenv("HAZEL_DEV_MODE", "false").strip().lower() == "true"


def require_synthetic_case_id(case_id: str) -> None:
    if not SYNTHETIC_CASE_PATTERN.fullmatch(case_id):
        raise HTTPException(422, "Development endpoints only support HAZEL-TEST-* synthetic cases.")


def require_dev_mode() -> None:
    if not DEV_MODE_ENABLED:
        raise HTTPException(404, "Not found")


def case_payload(conn, case_id: str):
    case = require_case(conn, case_id)
    if not case:
        raise HTTPException(404, "Onboarding case not found")
    submission = conn.execute(
        "SELECT legal_name, contact_email FROM express_interest_submissions WHERE case_id = %s",
        (case_id,),
    ).fetchone()
    return {
        **case,
        "legal_name": submission["legal_name"] if submission else None,
        "primary_applicant_email": submission["contact_email"] if submission else None,
    }


@router.post("/create-case", status_code=201)
def create_case(payload: DevCaseCreate):
    require_synthetic_case_id(payload.case_id)
    now = utc_now()
    with connection() as conn:
        if require_case(conn, payload.case_id):
            raise HTTPException(409, "A Hazel onboarding case with this ID already exists.")
        conn.execute(
            """INSERT INTO onboarding_cases
            (id, institution_id, current_stage, review_status, hazel_review_status,
             additional_information_required, created_at, updated_at)
            VALUES (%s, %s, 'NDA_PENDING', 'Not started', NULL, false, %s, %s)""",
            (payload.case_id, f"LOCAL-{payload.case_id}", now, now),
        )
        conn.execute(
            """INSERT INTO express_interest_submissions
            (case_id, legal_name, fdic_certificate_number, institution_type, website,
             contact_email, data_json, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                payload.case_id,
                payload.legal_name,
                payload.fdic_certificate_number,
                payload.institution_type,
                payload.website,
                payload.primary_applicant_email,
                Jsonb({"primary_applicant_email": payload.primary_applicant_email}),
                now,
            ),
        )
        conn.execute(
            "INSERT INTO institution_profiles (case_id, additional_responses_json, updated_at) VALUES (%s, '{}', %s)",
            (payload.case_id, now),
        )
        conn.execute(
            "INSERT INTO due_diligence (case_id, data_json, updated_at) VALUES (%s, '{}', %s)",
            (payload.case_id, now),
        )
        created = case_payload(conn, payload.case_id)
    logger.info("[Hazel] created synthetic onboarding case %s", payload.case_id)
    return created


@router.post("/reset-case/{case_id}")
def reset_case(case_id: str):
    require_synthetic_case_id(case_id)
    with connection() as conn:
        case = require_case(conn, case_id)
        if not case:
            raise HTTPException(404, "Onboarding case not found")
        stored_names = [
            row["stored_name"]
            for row in conn.execute(
                "SELECT stored_name FROM documents WHERE case_id = %s", (case_id,)
            ).fetchall()
        ]
        remote_session_id = case.get("coverbase_session_id")
        now = utc_now()
        conn.execute(
            """UPDATE onboarding_cases SET
            current_stage = 'NDA_PENDING', nda_accepted_at = NULL,
            institution_profile_completed_at = NULL, documents_completed_at = NULL,
            due_diligence_completed_at = NULL, risk_questions_submitted_at = NULL,
            hazel_review_status = NULL, review_status = 'Not started',
            additional_information_required = false,
            coverbase_session_id = NULL, coverbase_vendor_id = NULL,
            coverbase_status = NULL, updated_at = %s
            WHERE id = %s""",
            (now, case_id),
        )
        conn.execute(
            """UPDATE institution_profiles SET admission_type = '',
            international_correspondent_relationships = '', has_dba = '',
            has_fintech_or_baas_programs = '', additional_responses_json = '{}',
            updated_at = %s WHERE case_id = %s""",
            (now, case_id),
        )
        conn.execute("DELETE FROM documents WHERE case_id = %s", (case_id,))
        conn.execute("DELETE FROM review_clarifications WHERE case_id = %s", (case_id,))
        # The DELETE from risk_answers that used to sit here is gone with the
        # table. It was the only remaining reference to it besides its own DDL —
        # nothing ever inserted or selected from it, because the real risk answers
        # live in Coverbase (see save_risk_answer in cases.py).
        conn.execute(
            """INSERT INTO due_diligence (case_id, data_json, updated_at) VALUES (%s, '{}', %s)
            ON CONFLICT(case_id) DO UPDATE SET data_json = '{}', updated_at = excluded.updated_at""",
            (case_id, now),
        )
        reset = case_payload(conn, case_id)

    # This handler is a plain `def`, so FastAPI already runs it in a worker
    # thread; the storage calls below may be Files API round trips.
    for stored_name in stored_names:
        try:
            storage.delete(stored_name)
        except OSError as exc:
            logger.warning("Could not remove reset-case upload %s: %s", stored_name, exc)
    logger.info(
        "[Hazel] reset synthetic onboarding case %s; remote Coverbase session was not deleted%s",
        case_id,
        f" ({remote_session_id})" if remote_session_id else "",
    )
    return {
        **reset,
        "remote_coverbase_session_deleted": False,
        "previous_coverbase_session_id": remote_session_id,
    }


@router.post("/cases/{case_id}/hazel-review/clarification", status_code=201)
def create_review_clarification(case_id: str, payload: DevClarificationCreate):
    """Create a synthetic Hazel-only review request for local workflow testing."""
    require_dev_mode()
    require_synthetic_case_id(case_id)
    now = utc_now()
    clarification_id = f"hzclar_{uuid4().hex}"
    with connection() as conn:
        case = require_case(conn, case_id)
        if not case:
            raise HTTPException(404, "Onboarding case not found")
        if case["current_stage"] != "HAZEL_REVIEW":
            raise HTTPException(409, "Synthetic clarifications require a case in Hazel Review.")
        if case["coverbase_status"] in {"accepted", "rejected"}:
            raise HTTPException(409, "A finalized Coverbase decision cannot receive a clarification.")
        if payload.replacement_of_hazel_document_id is not None:
            replacement = conn.execute(
                "SELECT id FROM documents WHERE id = %s AND case_id = %s",
                (payload.replacement_of_hazel_document_id, case_id),
            ).fetchone()
            if not replacement:
                raise HTTPException(422, "Replacement document does not belong to this case.")
        conn.execute(
            """INSERT INTO review_clarifications
            (id, case_id, source, source_reference_id, requested_by,
             request_text, request_type, question_id, requested_at, due_at,
             status, member_response, submitted_at, document_required,
             document_label, replacement_of_hazel_document_id,
             uploaded_hazel_document_id, coverbase_sync_status, created_at, updated_at)
            VALUES (%s, %s, 'hazel_dev', NULL, 'Hazel Review Team', %s,
                    'additional_information', NULL, %s, %s, 'open', '', NULL,
                    %s, %s, %s, NULL, 'not_started', %s, %s)""",
            (
                clarification_id,
                case_id,
                payload.request_text,
                now,
                payload.due_at,
                payload.document_required,  # boolean column now, no int() cast
                payload.document_label,
                payload.replacement_of_hazel_document_id,
                now,
                now,
            ),
        )
        conn.execute(
            """UPDATE onboarding_cases SET additional_information_required = true,
            hazel_review_status = 'action_required',
            review_status = 'Action required — additional information requested',
            updated_at = %s WHERE id = %s""",
            (now, case_id),
        )
        created = conn.execute(
            "SELECT * FROM review_clarifications WHERE id = %s", (clarification_id,)
        ).fetchone()
    logger.info(
        "[Hazel] created synthetic review clarification %s for case %s",
        clarification_id,
        case_id,
    )
    return clarification_payload(created)
