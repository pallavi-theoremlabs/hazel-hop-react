import logging
from uuid import uuid4, uuid5, NAMESPACE_URL

from fastapi import APIRouter, HTTPException
from psycopg.types.json import Jsonb

from app.db import connection, utc_now
from app.schemas import SubmitInterestCreate
from app.tenancy import SYSTEM_SESSION
from app.services.rafa import (
    RafaAuthenticationError,
    RafaNotFound,
    RafaProviderUnavailable,
    rafa_service,
)

router = APIRouter(prefix="/api/public", tags=["public-onboarding"])
logger = logging.getLogger("uvicorn.error")


def org_id_for_certificate(fdic_certificate: str) -> str:
    """The organisation that owns everything about one institution.

    Derived rather than allocated, so the same bank inquiring twice lands in the
    same tenant instead of accumulating one organisation per submission. uuid5 is
    a pure function of the certificate number, which also means it needs no lookup
    and cannot race two concurrent first-time inquiries into two different orgs.

    The FDIC certificate is the right key because it is the identity RAFA screens
    on and the one field this endpoint has already validated as authentic — the
    legal name is user-supplied text and would let two spellings of one bank become
    two tenants.
    """
    return str(uuid5(NAMESPACE_URL, f"hazel-org:fdic:{fdic_certificate}"))


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

    org_id = org_id_for_certificate(bank["fdic_certificate_number"])
    institution_id = (
        f"RSSD-{bank['rssd_id']}"
        if bank["rssd_id"]
        else f"FDIC-{bank['fdic_certificate_number']}"
    )

    # SYSTEM, which is the anonymous-intake context hazel_schema.sql defines for
    # exactly this endpoint: a prospective member has no institution to present
    # until it has been screened, and the p_intake policies grant INSERT (and only
    # INSERT) under this role.
    #
    # Passed explicitly rather than inherited from the request because there is no
    # request tenancy here — /api/public is mounted with require_proxy alone.
    #
    # WARNING: every statement in this block still names tables from the retired
    # backend/migrations/ model — organizations, institutions, rafa_screenings,
    # onboarding_cases, express_interest_submissions, institution_profiles,
    # due_diligence. None exist in the final schema, so this endpoint fails on the
    # first INSERT with UndefinedTable. Fixing the call signature below stops it
    # failing for the *wrong* reason; it does not make the endpoint work. See the
    # four-table question in docs/ before porting the body.
    with connection(session=SYSTEM_SESSION) as conn:
        # First, and inside the same transaction as everything below: every tenant
        # table's org_id DEFAULT resolves to this id and carries a foreign key to
        # this row, so the organisation has to exist before the first of them.
        # hazel.organizations is deliberately outside RLS (migration 002), which is
        # what makes it writable here.
        conn.execute(
            """INSERT INTO organizations (id, slug, name)
               VALUES (%s, %s, %s)
               ON CONFLICT (id) DO NOTHING""",
            (
                org_id,
                f"fdic-{bank['fdic_certificate_number']}",
                bank["legal_name"],
            ),
        )
        conn.execute(
            """INSERT INTO institutions
            (id, legal_name, fdic_certificate, rssd_id, institution_type,
             registration_contact_email, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (org_id, id) DO UPDATE SET legal_name = excluded.legal_name,
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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (org_id, institution_id) DO UPDATE SET
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
            VALUES (%s, %s, %s, 'Not started', NULL, false, %s, %s)""",
            (case_id, institution_id, current_stage, now, now),
        )
        conn.execute(
            """INSERT INTO express_interest_submissions
            (case_id, legal_name, fdic_certificate_number, rssd_id, institution_type,
             website, headquarters, contact_name, contact_title, contact_email,
             data_json, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
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
                # data_json is jsonb. Postgres has no assignment cast from text to
                # jsonb, so json.dumps() here would fail outright.
                Jsonb(inquiry_context),
                now,
            ),
        )
        # Onboarding scaffolding, only for an inquiry that can actually onboard. A
        # rejected case is terminal — update_stage() refuses to advance it — so
        # empty profile and due-diligence rows would be permanently unreachable
        # scaffolding that still shows up in every count of in-flight applications.
        # The inquiry itself is kept in full: express_interest_submissions and
        # rafa_screenings above record who applied and why they were turned down.
        if eligible:
            conn.execute(
                "INSERT INTO institution_profiles (case_id, additional_responses_json, updated_at) VALUES (%s, '{}', %s)",
                (case_id, now),
            )
            conn.execute(
                "INSERT INTO due_diligence (case_id, data_json, updated_at) VALUES (%s, '{}', %s)",
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
        # The tenant this inquiry now belongs to. Returned so the Azure BFF can
        # bind the authenticated end user to it — every subsequent /api/cases call
        # sends it back as X-Hazel-Org-Id, and it is the only way the case becomes
        # reachable again, since RLS scopes every read to it.
        "org_id": org_id,
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
