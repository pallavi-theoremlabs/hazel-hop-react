from __future__ import annotations

import logging
from uuid import uuid4, uuid5, NAMESPACE_URL

from fastapi import APIRouter, HTTPException

from app.db import connection, utc_now
from app.schemas import SubmitInterestCreate
from app.services.rafa import (
    RafaAuthenticationError,
    RafaNotFound,
    RafaProviderUnavailable,
    rafa_service,
)

router = APIRouter(prefix="/api", tags=["public-onboarding"])
logger = logging.getLogger("uvicorn.error")


INSTITUTION_TYPES = {
    "national bank": "NATIONAL_BANK",
    "state member bank": "STATE_MEMBER_BANK",
    "state nonmember bank": "STATE_NONMEMBER_BANK",
    "savings institution": "SAVINGS_INSTITUTION",
    "credit union": "CREDIT_UNION",
    "trust company": "TRUST_COMPANY",
}


def institution_id_for_certificate(fdic_certificate: str) -> str:
    """The tenant identifier for one FDIC-screened institution.

    Derived rather than allocated, so the same bank inquiring twice lands in the
    same tenant instead of accumulating one institution per submission. uuid5 is
    a pure function of the certificate number, which also means it needs no lookup
    and cannot race two concurrent first-time inquiries into two tenants.

    The FDIC certificate is the right key because it is the identity RAFA screens
    on and the one field this endpoint has already validated as authentic — the
    legal name is user-supplied text and would let two spellings of one bank become
    two tenants.
    """
    return str(uuid5(NAMESPACE_URL, f"hazel-org:fdic:{fdic_certificate}"))


def institution_type_for_schema(value: str) -> str:
    """Translate the public form's labels into ck_institution_type values."""
    return INSTITUTION_TYPES.get(value.strip().lower(), "OTHER")


def pending_user_id_for_email(email: str) -> str:
    """Stable local identity for a contact who has not enrolled in Entra yet."""
    return str(uuid5(NAMESPACE_URL, f"hazel-pending-user:{email.strip().lower()}"))


def contact_name_parts(name: str) -> tuple[str, str | None]:
    first_name, separator, last_name = name.strip().partition(" ")
    return first_name, last_name if separator else None


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


@router.get("/banks/{fdic_cert_number}")
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

    submission_id = uuid4()
    suffix = submission_id.hex[:12].upper()
    case_id = str(submission_id)
    inquiry_reference = f"HZL-INT-{suffix}"
    now = utc_now()
    eligible = bank["rafa_status"] == "accepted"
    api_stage = "NDA_PENDING" if eligible else "INQUIRY_REJECTED"
    database_stage = "NDA" if eligible else "ELIGIBILITY_SCREENING"
    database_status = "AWAITING_MEMBER" if eligible else "DECLINED"
    decision_status = "PENDING" if eligible else "DECLINED"
    institution_status = "ONBOARDING" if eligible else "DECLINED"
    rafa_status = "PASS" if eligible else "DECLINE"
    invitation_status = "approved_mock" if eligible else "not_created"
    institution_id = institution_id_for_certificate(bank["fdic_certificate_number"])
    user_id = pending_user_id_for_email(payload.contact_email)
    first_name, last_name = contact_name_parts(payload.contact_name)

    # SYSTEM is the server-chosen anonymous-intake role. Supplying the institution
    # id as well is load-bearing: p_intake permits the first institution, user and
    # case inserts, while p_tenant permits the RAFA projection and makes repeat
    # submissions for this same institution visible to their upserts.
    with connection(session=(institution_id, None, "SYSTEM")) as conn:
        # Serialize submissions for one FDIC certificate. Without this, two clicks
        # can both observe no active case and race into ux_case_one_active.
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (institution_id,),
        )
        conn.execute(
            """INSERT INTO institution
            (id, legal_name, fdic_certificate, institution_type, status,
             registration_contact_email, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
            legal_name = excluded.legal_name,
            fdic_certificate = excluded.fdic_certificate,
            institution_type = excluded.institution_type,
            status = CASE
                WHEN institution.status IN ('ACTIVE', 'SUSPENDED')
                THEN institution.status ELSE excluded.status END,
            registration_contact_email = excluded.registration_contact_email,
            updated_at = excluded.updated_at""",
            (
                institution_id,
                bank["legal_name"],
                bank["fdic_certificate_number"],
                institution_type_for_schema(payload.institution_type),
                institution_status,
                payload.contact_email,
                now,
                now,
            ),
        )
        conn.execute(
            """INSERT INTO "user"
            (id, institution_id, external_identity_id, email, first_name,
             last_name, role, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'MEMBER_ADMIN', %s, %s)
            ON CONFLICT (email) DO UPDATE SET
            first_name = excluded.first_name,
            last_name = excluded.last_name,
            updated_at = excluded.updated_at""",
            (
                user_id,
                institution_id,
                f"pending-inquiry:{user_id}",
                payload.contact_email,
                first_name,
                last_name,
                now,
                now,
            ),
        )

        if eligible:
            active_case = conn.execute(
                """SELECT id, case_number FROM onboarding_case
                   WHERE institution_id = %s
                     AND current_status NOT IN ('COMPLETED', 'DECLINED')
                   ORDER BY created_at DESC LIMIT 1""",
                (institution_id,),
            ).fetchone()
        else:
            active_case = None

        if active_case:
            case_id = str(active_case["id"])
            inquiry_reference = active_case["case_number"]
        else:
            conn.execute(
                """INSERT INTO onboarding_case
                (id, institution_id, case_number, current_stage, current_status,
                 decision_status, coverbase_sync_status, created_at, completed_at,
                 updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'NOT_APPLICABLE', %s, %s, %s)""",
                (
                    case_id,
                    institution_id,
                    inquiry_reference,
                    database_stage,
                    database_status,
                    decision_status,
                    now,
                    None if eligible else now,
                    now,
                ),
            )

        # Insert RAFA after the case. trg_propagate then copies the score into the
        # protected onboarding_case.rafa_score column, which hop_app cannot update.
        conn.execute(
            """INSERT INTO rafa
            (institution_id, fdic_certificate, rssd_id, rafa_score, rafa_status,
             fetched_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (institution_id) DO UPDATE SET
            fdic_certificate = excluded.fdic_certificate,
            rssd_id = excluded.rssd_id,
            rafa_score = excluded.rafa_score,
            rafa_status = excluded.rafa_status,
            fetched_at = excluded.fetched_at,
            updated_at = excluded.updated_at""",
            (
                institution_id,
                bank["fdic_certificate_number"],
                bank["rssd_id"],
                bank["rafa_score"],
                rafa_status,
                now,
                now,
            ),
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
        # The tenant this inquiry now belongs to. Returned so the Azure BFF can
        # bind the authenticated end user to it — every subsequent /api/cases call
        # sends it back as X-Hazel-Institution-Id, and it is the only way the case
        # becomes reachable again, since RLS scopes every read to it.
        "org_id": institution_id,
        "inquiry_reference": inquiry_reference,
        "institution_id": institution_id,
        "legal_name": bank["legal_name"],
        "fdic_certificate_number": bank["fdic_certificate_number"],
        "rssd_id": bank["rssd_id"],
        "current_stage": api_stage,
        "rafa_score": bank["rafa_score"],
        "rafa_status": bank["rafa_status"],
        "eligible": eligible,
        "invitation_status": invitation_status,
        "coverbase_session_id": None,
        "next_path": f"/case/{case_id}/nda" if eligible else None,
        "local_dev_workflow": eligible,
    }
