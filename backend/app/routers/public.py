import logging
from uuid import uuid4

from fastapi import APIRouter
from psycopg.types.json import Jsonb

from app.db import connection, utc_now
from app.schemas import SubmitInterestCreate

router = APIRouter(prefix="/api/public", tags=["public-onboarding"])
logger = logging.getLogger("uvicorn.error")


@router.post("/submit-interest", status_code=201)
def submit_interest(payload: SubmitInterestCreate):
    """Create a Hazel-owned inquiry and local test case without calling Coverbase."""
    suffix = uuid4().hex[:12].upper()
    case_id = f"HAZEL-TEST-INQUIRY-{suffix}"
    inquiry_reference = f"HZL-INT-{suffix}"
    now = utc_now()
    inquiry_context = {
        "phone": payload.phone,
        "reason_for_interest": payload.reason_for_interest,
        "inquiry_reference": inquiry_reference,
        "source": "public_submit_interest",
        "local_dev_workflow": True,
        "rafa_status": "approved_mock",
        "invitation_status": "approved_mock",
    }

    with connection() as conn:
        conn.execute(
            """INSERT INTO onboarding_cases
            (id, institution_id, current_stage, review_status, hazel_review_status,
             additional_information_required, created_at, updated_at)
            VALUES (%s, %s, 'NDA_PENDING', 'Not started', NULL, false, %s, %s)""",
            (case_id, f"LOCAL-INQUIRY-{suffix}", now, now),
        )
        conn.execute(
            """INSERT INTO express_interest_submissions
            (case_id, legal_name, fdic_certificate_number, institution_type, website,
             contact_name, contact_title, contact_email, data_json, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                case_id,
                payload.legal_name,
                payload.fdic_certificate_number,
                payload.institution_type,
                payload.website,
                payload.contact_name,
                payload.contact_title,
                payload.contact_email,
                # data_json is jsonb. Postgres has no assignment cast from text to
                # jsonb, so json.dumps() here would fail outright.
                Jsonb(inquiry_context),
                now,
            ),
        )
        conn.execute(
            "INSERT INTO institution_profiles (case_id, additional_responses_json, updated_at) VALUES (%s, '{}', %s)",
            (case_id, now),
        )
        conn.execute(
            "INSERT INTO due_diligence (case_id, data_json, updated_at) VALUES (%s, '{}', %s)",
            (case_id, now),
        )

    logger.info(
        "[Hazel] received Submit Interest inquiry %s and created local case %s; "
        "RAFA and invitation approved in local dev mode",
        inquiry_reference,
        case_id,
    )
    return {
        "case_id": case_id,
        "inquiry_reference": inquiry_reference,
        "current_stage": "NDA_PENDING",
        "rafa_status": "approved_mock",
        "invitation_status": "approved_mock",
        "coverbase_session_id": None,
        "next_path": f"/case/{case_id}/nda",
        "local_dev_workflow": True,
    }
