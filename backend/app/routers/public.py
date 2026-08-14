import json
import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.db import connection, utc_now
from app.schemas import SubmitInterestCreate
from app.services.rafa import (
    RafaAuthenticationError,
    RafaNotFound,
    RafaProviderUnavailable,
    rafa_service,
)

router = APIRouter(prefix="/api/public", tags=["public-onboarding"])
logger = logging.getLogger("uvicorn.error")


def public_rafa_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RafaNotFound):
        return HTTPException(
            404,
            "We could not find an institution matching that FDIC certificate number.",
        )
    if isinstance(exc, RafaAuthenticationError):
        logger.error("[RAFA] lookup unavailable because backend authentication failed")
    return HTTPException(
        503,
        "Institution verification is temporarily unavailable. Please try again.",
    )


@router.get("/banks/fdic/{fdic_cert_number}")
async def lookup_bank_by_fdic(fdic_cert_number: str):
    if not fdic_cert_number.isdigit() or len(fdic_cert_number) > 10:
        raise HTTPException(
            422, "Enter the FDIC certificate number using digits only."
        )
    try:
        return await rafa_service.lookup_bank(fdic_cert_number)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (RafaNotFound, RafaAuthenticationError, RafaProviderUnavailable) as exc:
        raise public_rafa_error(exc) from exc


@router.post("/submit-interest", status_code=201)
async def submit_interest(payload: SubmitInterestCreate):
    """Screen and persist a Hazel inquiry without creating a Coverbase intake."""
    try:
        bank = await rafa_service.lookup_bank(payload.fdic_certificate_number)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (RafaNotFound, RafaAuthenticationError, RafaProviderUnavailable) as exc:
        raise public_rafa_error(exc) from exc

    suffix = uuid4().hex[:12].upper()
    case_id = f"HAZEL-TEST-INQUIRY-{suffix}"
    inquiry_reference = f"HZL-INT-{suffix}"
    now = utc_now()
    eligible = bank["rafa_status"] == "accepted"
    current_stage = "NDA_PENDING" if eligible else "INQUIRY_REJECTED"
    invitation_status = "approved_mock" if eligible else "not_created"
    inquiry_context = {
        "phone": payload.phone,
        "reason_for_interest": payload.reason_for_interest,
        "inquiry_reference": inquiry_reference,
        "source": "public_submit_interest",
        "local_dev_workflow": eligible,
        "rafa_status": bank["rafa_status"],
        "rafa_score": bank["rafa_score"],
        "invitation_status": invitation_status,
    }

    with connection() as conn:
        existing = conn.execute(
            "SELECT id FROM institutions WHERE fdic_certificate = ?",
            (bank["fdic_certificate_number"],),
        ).fetchone()
        institution_id = (
            existing["id"]
            if existing
            else (
                f"RSSD-{bank['rssd_id']}"
                if bank["rssd_id"]
                else f"FDIC-{bank['fdic_certificate_number']}"
            )
        )
        conn.execute(
            """INSERT INTO institutions
            (id, legal_name, fdic_certificate, rssd_id, institution_type,
             registration_contact_email, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET legal_name = excluded.legal_name,
            fdic_certificate = excluded.fdic_certificate,
            rssd_id = excluded.rssd_id,
            institution_type = excluded.institution_type,
            registration_contact_email = excluded.registration_contact_email,
            updated_at = excluded.updated_at""",
            (
                institution_id,
                bank["legal_name"],
                bank["fdic_certificate_number"],
                bank["rssd_id"],
                payload.institution_type,
                payload.contact_email,
                now,
            ),
        )
        conn.execute(
            """INSERT INTO rafa_screenings
            (institution_id, fdic_certificate, rssd_id, rafa_score, rafa_status,
             rating_label, composite_rating, profile_year, profile_quarter, screened_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(institution_id) DO UPDATE SET
            fdic_certificate = excluded.fdic_certificate,
            rssd_id = excluded.rssd_id, rafa_score = excluded.rafa_score,
            rafa_status = excluded.rafa_status,
            rating_label = excluded.rating_label,
            composite_rating = excluded.composite_rating,
            profile_year = excluded.profile_year,
            profile_quarter = excluded.profile_quarter,
            screened_at = excluded.screened_at""",
            (
                institution_id,
                bank["fdic_certificate_number"],
                bank["rssd_id"],
                bank["rafa_score"],
                bank["rafa_status"],
                bank["rating_label"],
                bank["composite_rating"],
                bank["profile_year"],
                bank["profile_quarter"],
                now,
            ),
        )
        conn.execute(
            """INSERT INTO onboarding_cases
            (id, institution_id, current_stage, review_status, hazel_review_status,
             additional_information_required, created_at, updated_at)
            VALUES (?, ?, ?, ?, NULL, 0, ?, ?)""",
            (
                case_id,
                institution_id,
                current_stage,
                "Not started" if eligible else "RAFA screening rejected",
                now,
                now,
            ),
        )
        conn.execute(
            """INSERT INTO express_interest_submissions
            (case_id, legal_name, fdic_certificate_number, rssd_id, institution_type,
             website, headquarters, contact_name, contact_title, contact_email,
             data_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                case_id,
                bank["legal_name"],
                bank["fdic_certificate_number"],
                bank["rssd_id"],
                payload.institution_type,
                payload.website,
                bank["headquarters"],
                payload.contact_name,
                payload.contact_title,
                payload.contact_email,
                json.dumps(inquiry_context),
                now,
            ),
        )
        if eligible:
            conn.execute(
                """INSERT INTO institution_profiles
                (case_id, legal_name, fdic_certificate_number, rssd_id,
                 institution_type, website, headquarters, additional_responses_json,
                 updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?)""",
                (
                    case_id,
                    bank["legal_name"],
                    bank["fdic_certificate_number"],
                    bank["rssd_id"],
                    payload.institution_type,
                    payload.website,
                    bank["headquarters"],
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO due_diligence (case_id, data_json, updated_at) VALUES (?, '{}', ?)",
                (case_id, now),
            )

    logger.info(
        "[Hazel] received Submit Interest inquiry %s for institution %s; "
        "RAFA status=%s; Coverbase session not created",
        inquiry_reference,
        institution_id,
        bank["rafa_status"],
    )
    return {
        "case_id": case_id,
        "inquiry_reference": inquiry_reference,
        "institution_id": institution_id,
        "legal_name": bank["legal_name"],
        "fdic_certificate_number": bank["fdic_certificate_number"],
        "rssd_id": bank["rssd_id"],
        "current_stage": current_stage,
        "rafa_score": bank["rafa_score"],
        "rafa_status": bank["rafa_status"],
        "eligible": eligible,
        "invitation_status": invitation_status,
        "coverbase_session_id": None,
        "next_path": f"/case/{case_id}/nda" if eligible else None,
        "local_dev_workflow": eligible,
    }
