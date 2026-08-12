import hashlib
import logging
import os
import re
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from psycopg.types.json import Jsonb

from app.config import BACKEND_DIR
from app.db import STAGES, connection, require_case, row_dict, update_stage, utc_now
from app.models import (
    ACTION_REQUIRED_STATUSES,
    UNRESOLVED_STATUSES,
    clarification_payload,
    review_state_for,
)
from app.schemas import (
    ClarificationDraftUpdate,
    DueDiligenceUpdate,
    InstitutionProfileResponsesUpdate,
    InstitutionProfileUpdate,
    RiskQuestionResponseUpdate,
)
from app.services.coverbase import (
    CoverbaseDocumentSyncError,
    CoverbaseQuestionnaireSavePending,
    CoverbaseSubmissionValidationError,
    InstitutionProfileQuestionsEmpty,
    coverbase_service,
)
from app.services.institution_profile_schema import (
    HAZEL_INSTITUTION_PROFILE_SCHEMA,
    is_valid_institution_profile_schema,
)

router = APIRouter(prefix="/api/cases", tags=["cases"])
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BACKEND_DIR / "uploads")))
if not UPLOAD_DIR.is_absolute():
    UPLOAD_DIR = BACKEND_DIR / UPLOAD_DIR
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
logger = logging.getLogger("uvicorn.error")

REVIEW_STATUS_MAP = {
    "submitted": ("under_review", "Processing / preparing for review"),
    "pending_review": ("under_review", "Under Hazel/Vantage review"),
    "accepted": ("approved", "Review complete"),
    "rejected": ("rejected", "Rejected"),
    "partial": ("partial", "Needs explicit handling"),
}


def ensure_upload_dir() -> Path:
    """Resolve and validate UPLOAD_DIR once, at startup.

    In production this points at a Unity Catalog Volume reached over FUSE, which
    behaves differently from a local filesystem and is only mountable from inside
    the App — so it cannot be exercised before deploy. Checking it here turns a
    misconfigured volume into a clear startup failure rather than a 500 on the
    first member upload, halfway through onboarding.

    This also replaces a per-request mkdir that ran on every single upload.
    """
    logger.info("[Hazel] UPLOAD_DIR resolved to %s", UPLOAD_DIR)
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        probe = UPLOAD_DIR / ".hazel-write-probe"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        raise RuntimeError(
            f"UPLOAD_DIR {UPLOAD_DIR} is not writable ({exc}). On Databricks Apps "
            "this is a Unity Catalog Volume path; check that it exists and that the "
            "app service principal holds READ VOLUME and WRITE VOLUME on it."
        ) from exc
    logger.info("[Hazel] UPLOAD_DIR is writable")
    return UPLOAD_DIR


def get_or_404(conn, case_id):
    case = require_case(conn, case_id)
    if not case:
        raise HTTPException(404, "Onboarding case not found")
    return case


# The three *_json columns are jsonb now, so psycopg hands back a parsed dict.
# These used to json.loads() a TEXT column; keeping that would pass a dict to
# json.loads, raise TypeError, and be swallowed by the except into {} — the data
# would silently vanish rather than fail.


def profile_payload(row):
    profile = row_dict(row)
    if not profile:
        return profile
    profile["additional_responses"] = profile.pop("additional_responses_json", None) or {}
    return profile


def express_interest_payload(row):
    submission = row_dict(row) or {}
    extra_data = submission.pop("data_json", None) or {}
    return {**extra_data, **submission}


def document_payload(row, session_document_ids=None):
    document = row_dict(row) or {}
    document["coverbase_sync_details"] = (
        document.pop("coverbase_sync_details_json", None) or {}
    )
    coverbase_document_id = document.get("coverbase_document_id")
    document["coverbase_in_session"] = (
        coverbase_document_id in session_document_ids
        if coverbase_document_id and session_document_ids is not None
        else document["coverbase_sync_details"].get("document_in_session")
    )
    return document


def load_review_clarifications(conn, case_id):
    rows = conn.execute(
        """SELECT * FROM review_clarifications
        WHERE case_id = %s ORDER BY requested_at DESC, created_at DESC""",
        (case_id,),
    ).fetchall()
    clarifications = []
    for row in rows:
        uploaded_document = None
        if row["uploaded_hazel_document_id"] is not None:
            document_row = conn.execute(
                "SELECT * FROM documents WHERE id = %s AND case_id = %s",
                (row["uploaded_hazel_document_id"], case_id),
            ).fetchone()
            if document_row:
                uploaded_document = document_payload(document_row)
        clarifications.append(clarification_payload(row, uploaded_document))
    return clarifications


def clarification_history_events(clarification):
    if not clarification:
        return []
    events = [
        {
            "type": "request_received",
            "label": "Request received",
            "occurred_at": clarification["requested_at"],
        }
    ]
    if clarification["status"] == "open":
        events.append(
            {
                "type": "awaiting_response",
                "label": "Awaiting your response",
                "occurred_at": clarification["updated_at"],
            }
        )
    if clarification["status"] == "draft":
        events.append(
            {
                "type": "draft_saved",
                "label": "Draft saved",
                "occurred_at": clarification["updated_at"],
            }
        )
    if clarification["status"] in {"submitted", "resolved"}:
        events.extend(
            [
                {
                    "type": "response_submitted",
                    "label": "Response submitted",
                    "occurred_at": clarification["submitted_at"],
                },
                {
                    "type": "review_resumed",
                    "label": "Review resumed",
                    "occurred_at": clarification["submitted_at"],
                },
            ]
        )
    return events


def backfill_case_document_hashes(conn, case_id):
    """Populate hashes for legacy Hazel rows from their locally stored files."""
    rows = conn.execute(
        "SELECT id, stored_name FROM documents WHERE case_id = %s AND file_sha256 IS NULL",
        (case_id,),
    ).fetchall()
    for row in rows:
        stored_path = UPLOAD_DIR / Path(row["stored_name"]).name
        try:
            contents = stored_path.read_bytes()
        except OSError:
            logger.warning(
                "Could not backfill SHA-256 for Hazel document %s", row["id"]
            )
            continue
        conn.execute(
            "UPDATE documents SET file_sha256 = %s WHERE id = %s",
            (hashlib.sha256(contents).hexdigest(), row["id"]),
        )


async def sync_hazel_document(case, document, contents=None):
    """Synchronize one persisted Hazel document without risking local data."""
    document_id = document["id"]
    session_id = case.get("coverbase_session_id")
    if not session_id:
        error = "This Hazel case does not have a Coverbase intake session."
        with connection() as conn:
            conn.execute(
                """UPDATE documents SET coverbase_sync_status = %s,
                coverbase_sync_error = %s, coverbase_sync_details_json = %s WHERE id = %s""",
                ("not_configured", error, Jsonb({}), document_id),
            )
            saved = conn.execute(
                "SELECT * FROM documents WHERE id = %s", (document_id,)
            ).fetchone()
        return {
            **document_payload(saved),
            "integration_warning": error,
        }

    existing_coverbase_id = document.get("coverbase_document_id")
    result = {}
    error = None
    try:
        if existing_coverbase_id:
            existing_details = document.get("coverbase_sync_details_json") or {}
            attachment = await coverbase_service.attach_intake_document(
                session_id, existing_coverbase_id
            )
            result = {
                **existing_details,
                **attachment,
                "duplicate_upload_prevented": True,
            }
        else:
            if contents is None:
                safe_stored_name = Path(document["stored_name"]).name
                stored_path = UPLOAD_DIR / safe_stored_name
                if not stored_path.is_file():
                    raise RuntimeError("Hazel's stored document file could not be found")
                contents = stored_path.read_bytes()
            file_sha256 = document.get("file_sha256") or hashlib.sha256(contents).hexdigest()
            if not document.get("file_sha256"):
                with connection() as conn:
                    conn.execute(
                        "UPDATE documents SET file_sha256 = %s WHERE id = %s",
                        (file_sha256, document_id),
                    )
                document["file_sha256"] = file_sha256
            with connection() as conn:
                reusable = conn.execute(
                    """SELECT id, coverbase_document_id FROM documents
                    WHERE case_id = %s AND id != %s AND file_sha256 = %s
                    AND coverbase_sync_status = 'synced'
                    AND coverbase_document_id IS NOT NULL
                    ORDER BY created_at, id LIMIT 1""",
                    (document["case_id"], document_id, file_sha256),
                ).fetchone()
            if reusable:
                attachment = await coverbase_service.attach_intake_document(
                    session_id, reusable["coverbase_document_id"]
                )
                result = {
                    **attachment,
                    "content_deduplicated": True,
                    "reused_from_hazel_document_id": reusable["id"],
                    "s3_upload_skipped": True,
                    "document_registration_skipped": True,
                    "duplicate_upload_prevented": True,
                }
                logger.info(
                    "[Hazel] reused Coverbase document %s for Hazel document %s by SHA-256",
                    reusable["coverbase_document_id"],
                    document_id,
                )
            else:
                result = await coverbase_service.sync_intake_document(
                    session_id,
                    document["original_name"],
                    contents,
                    Path(document["original_name"]).suffix,
                )
                result["content_deduplicated"] = False
                result["duplicate_upload_prevented"] = False
        status = "synced"
    except CoverbaseDocumentSyncError as exc:
        result = exc.result
        error = str(exc)
        status = "failed"
    except (OSError, RuntimeError) as exc:
        error = str(exc)
        status = "failed"

    coverbase_document_id = (
        result.get("coverbase_document_id") or existing_coverbase_id
    )
    synced_at = utc_now() if status == "synced" else None
    with connection() as conn:
        conn.execute(
            """UPDATE documents SET coverbase_document_id = %s,
            coverbase_sync_status = %s, coverbase_synced_at = %s,
            coverbase_sync_error = %s, coverbase_sync_details_json = %s
            WHERE id = %s""",
            (
                coverbase_document_id,
                status,
                synced_at,
                error,
                Jsonb(result),
                document_id,
            ),
        )
        saved = conn.execute(
            "SELECT * FROM documents WHERE id = %s", (document_id,)
        ).fetchone()
    logger.info(
        "[Hazel] document %s Coverbase sync status %s%s",
        document_id,
        status,
        f" ({coverbase_document_id})" if coverbase_document_id else "",
    )
    payload = document_payload(
        saved,
        {coverbase_document_id}
        if result.get("document_in_session") and coverbase_document_id
        else set(),
    )
    if error:
        payload["integration_warning"] = (
            "The document is stored safely in Hazel, but Coverbase synchronization "
            f"did not complete: {error}"
        )
    return payload


def stage_index(stage):
    return STAGES.index(stage)


def require_at_least(case, stage):
    if stage_index(case["current_stage"]) < stage_index(stage):
        raise HTTPException(409, f"Complete the prior onboarding stage before {stage.replace('_', ' ').title()}.")


@router.get("/{case_id}")
def get_case(case_id: str):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        submission = conn.execute(
            "SELECT legal_name, contact_email FROM express_interest_submissions WHERE case_id = %s",
            (case_id,),
        ).fetchone()
        case["legal_name"] = submission["legal_name"] if submission else None
        case["primary_applicant_email"] = submission["contact_email"] if submission else None
        case["additional_information_required"] = bool(case["additional_information_required"])
        case["esign_eligible"] = case["coverbase_status"] == "accepted"
        return case


async def ensure_coverbase_session(case_id: str):
    """Create one Coverbase session after NDA acceptance, never during public intake."""
    with connection() as conn:
        case = get_or_404(conn, case_id)
        if not case["nda_accepted_at"]:
            raise HTTPException(409, "Accept the NDA before creating a Coverbase intake session.")
        if case["coverbase_session_id"]:
            logger.info("[Coverbase] reused session %s", case["coverbase_session_id"])
            return {
                "session_id": case["coverbase_session_id"],
                "vendor_id": case["coverbase_vendor_id"],
                "status": case["coverbase_status"] or "created",
                "reused": True,
            }
        express_interest_row = conn.execute(
            "SELECT * FROM express_interest_submissions WHERE case_id = %s", (case_id,)
        ).fetchone()
        if not express_interest_row:
            raise HTTPException(409, "Hazel Express Interest data is required before creating a Coverbase session.")
        express_interest = express_interest_payload(express_interest_row)

    try:
        session = await coverbase_service.create_intake_session(case_id, express_interest, {})
    except (httpx.HTTPError, RuntimeError) as exc:
        with connection() as conn:
            conn.execute(
                "UPDATE onboarding_cases SET coverbase_status = %s, updated_at = %s WHERE id = %s",
                ("error", utc_now(), case_id),
            )
        raise HTTPException(502, f"Coverbase intake session could not be created: {exc}") from exc

    session_id = session.get("id") or session.get("session_id")
    if not session_id:
        raise HTTPException(502, "Coverbase response did not include a session ID")
    with connection() as conn:
        conn.execute(
            """UPDATE onboarding_cases
            SET coverbase_session_id = %s, coverbase_vendor_id = %s, coverbase_status = %s, updated_at = %s
            WHERE id = %s AND coverbase_session_id IS NULL""",
            (
                session_id,
                session.get("vendor_id"),
                session.get("status", "processing"),
                utc_now(),
                case_id,
            ),
        )
        stored = get_or_404(conn, case_id)
    if stored["coverbase_session_id"] != session_id:
        logger.warning("Concurrent Coverbase session creation detected for case %s", case_id)
        logger.info("[Coverbase] reused session %s", stored["coverbase_session_id"])
        return {
            "session_id": stored["coverbase_session_id"],
            "vendor_id": stored["coverbase_vendor_id"],
            "status": stored["coverbase_status"],
            "reused": True,
        }
    logger.info("[Coverbase] created session %s", session_id)
    try:
        await coverbase_service.generate_institution_profile_questions(
            session_id, express_interest.get("legal_name") or ""
        )
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        logger.warning(
            "Coverbase session %s was created, but Institution Profile generation is not ready: %s",
            session_id,
            exc,
        )
    return session


@router.post("/{case_id}/nda/accept")
async def accept_nda(case_id: str):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        now = case["nda_accepted_at"] or utc_now()
        update_stage(conn, case_id, "INSTITUTION_PROFILE", nda_accepted_at=now)
    response = {"accepted_at": now, "current_stage": "INSTITUTION_PROFILE"}
    try:
        session = await ensure_coverbase_session(case_id)
        response.update(
            coverbase_session_id=session.get("id") or session.get("session_id"),
            coverbase_status=session.get("status", "created"),
        )
    except HTTPException as exc:
        logger.error("NDA accepted, but Coverbase session creation failed for %s: %s", case_id, exc.detail)
        response.update(coverbase_session_id=None, coverbase_status="error", warning=exc.detail)
    return response


@router.post("/{case_id}/coverbase/session")
async def create_coverbase_session(case_id: str):
    return await ensure_coverbase_session(case_id)


@router.get("/{case_id}/institution-profile")
def get_institution_profile(case_id: str):
    with connection() as conn:
        get_or_404(conn, case_id)
        return profile_payload(conn.execute("SELECT * FROM institution_profiles WHERE case_id = %s", (case_id,)).fetchone())


async def load_institution_profile_schema(case_id: str):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        submission = express_interest_payload(
            conn.execute(
                "SELECT * FROM express_interest_submissions WHERE case_id = %s", (case_id,)
            ).fetchone()
        )
    if case["coverbase_session_id"]:
        try:
            schema = await coverbase_service.get_institution_profile_questions(
                case["coverbase_session_id"]
            )
            if is_valid_institution_profile_schema(schema):
                logger.info("[Coverbase] fetched institution-profile context")
                return {**schema, "source": "coverbase"}
        except InstitutionProfileQuestionsEmpty:
            try:
                schema = await coverbase_service.generate_institution_profile_questions(
                    case["coverbase_session_id"], submission.get("legal_name") or ""
                )
                if is_valid_institution_profile_schema(schema):
                    logger.info("[Coverbase] fetched institution-profile context")
                    return {**schema, "source": "coverbase"}
            except InstitutionProfileQuestionsEmpty as exc:
                logger.warning(
                    "Coverbase Step 1 completed and follow-up polling expired for session %s; "
                    "using Hazel fallback: %s",
                    case["coverbase_session_id"],
                    exc,
                )
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                logger.error(
                    "Coverbase Step 1 integration failed for session %s: %s",
                    case["coverbase_session_id"],
                    exc,
                )
                raise HTTPException(
                    502,
                    f"Coverbase Institution Profile generation failed: {exc}",
                ) from exc
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            logger.error(
                "Coverbase Institution Profile lookup failed for session %s: %s",
                case["coverbase_session_id"],
                exc,
            )
            raise HTTPException(
                502,
                f"Coverbase Institution Profile lookup failed: {exc}",
            ) from exc
    logger.info("[Coverbase] using Hazel fallback schema")
    return {**HAZEL_INSTITUTION_PROFILE_SCHEMA, "source": "fallback"}


@router.get("/{case_id}/institution-profile/schema")
async def get_institution_profile_schema(case_id: str):
    return await load_institution_profile_schema(case_id)


@router.get("/{case_id}/institution-profile/questions")
async def get_institution_profile_questions(case_id: str):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        require_at_least(case, "INSTITUTION_PROFILE")
        profile = profile_payload(
            conn.execute("SELECT * FROM institution_profiles WHERE case_id = %s", (case_id,)).fetchone()
        )
    schema = await load_institution_profile_schema(case_id)
    coverbase_responses = schema.get("responses", {})
    hazel_responses = (profile or {}).get("additional_responses", {})
    return {**schema, "responses": {**hazel_responses, **coverbase_responses}}


@router.post("/{case_id}/institution-profile/responses")
async def save_institution_profile_responses(
    case_id: str, payload: InstitutionProfileResponsesUpdate
):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        require_at_least(case, "INSTITUTION_PROFILE")
        coverbase_session_id = case["coverbase_session_id"]
        submit_interest = express_interest_payload(
            conn.execute(
                "SELECT * FROM express_interest_submissions WHERE case_id = %s",
                (case_id,),
            ).fetchone()
        )
        now = utc_now()
        known_storage_keys = {
            question["id"]: question["storage_key"]
            for section in HAZEL_INSTITUTION_PROFILE_SCHEMA["sections"]
            for question in section.get("questions", [])
            if question.get("storage_key")
        }
        mapped_values = {}
        for question_id, storage_key in known_storage_keys.items():
            response = payload.responses.get(question_id, {})
            if isinstance(response, dict):
                mapped_values[storage_key] = response.get("choice") or response.get("custom") or ""
            elif isinstance(response, str):
                mapped_values[storage_key] = response
        assignments = ["additional_responses_json = %s", "updated_at = %s"]
        values = [Jsonb(payload.responses), now]
        for storage_key, value in mapped_values.items():
            assignments.append(f"{storage_key} = %s")
            values.append(value)
        insert_columns = ["case_id", "additional_responses_json", "updated_at", *mapped_values]
        insert_values = [case_id, Jsonb(payload.responses), now, *mapped_values.values()]
        conn.execute(
            f"""INSERT INTO institution_profiles ({', '.join(insert_columns)})
            VALUES ({', '.join('%s' for _ in insert_columns)})
            ON CONFLICT(case_id) DO UPDATE SET {', '.join(assignments)}""",
            insert_values + values,
        )
        logger.info("[Hazel] saved institution-profile responses for case %s", case_id)

    result = {
        "responses": payload.responses,
        "updated_at": now,
        "source": "hazel",
        "coverbase_response_sync": "not_applicable",
        "coverbase_questionnaire_processing": False,
    }
    if coverbase_service.mode != "live" or not coverbase_session_id:
        return result

    try:
        sync = await coverbase_service.sync_institution_profile_responses(
            coverbase_session_id, payload.responses, submit_interest
        )
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        logger.error(
            "[Coverbase] Institution Profile response sync failed for case %s, session %s: %s",
            case_id,
            coverbase_session_id,
            exc,
        )
        raise HTTPException(
            502,
            {
                "message": (
                    "Institution Profile responses were saved to Hazel, but Coverbase "
                    "synchronization failed. Please retry before continuing."
                ),
                "coverbase_response_sync": "error",
            },
        ) from exc

    return {
        **result,
        "coverbase_response_sync": "synced",
        "coverbase_questionnaire_processing": sync["questionnaire_processing"],
        "coverbase_questionnaire_responses_populated": sync[
            "questionnaire_responses_populated"
        ],
        "coverbase_questionnaire_response_count": sync[
            "questionnaire_response_count"
        ],
        "coverbase_mapped_responses": sync["mapped_responses"],
        "coverbase_followups_updated": sync["updated_followups"],
        "coverbase_process_all_questions_status": sync[
            "process_all_questions_status"
        ],
    }


@router.put("/{case_id}/institution-profile")
def save_institution_profile(case_id: str, payload: InstitutionProfileUpdate):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        require_at_least(case, "INSTITUTION_PROFILE")
        data = payload.model_dump()
        additional_responses = data.pop("additional_responses", {})
        columns = list(data.keys())
        assignments = ", ".join(f"{column} = %s" for column in columns)
        conn.execute(
            f"UPDATE institution_profiles SET {assignments}, additional_responses_json = %s, updated_at = %s WHERE case_id = %s",
            [data[c] for c in columns] + [Jsonb(additional_responses), utc_now(), case_id],
        )
        return profile_payload(conn.execute("SELECT * FROM institution_profiles WHERE case_id = %s", (case_id,)).fetchone())


@router.post("/{case_id}/institution-profile/complete")
def complete_institution_profile(case_id: str):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        require_at_least(case, "INSTITUTION_PROFILE")
        profile = profile_payload(
            conn.execute("SELECT * FROM institution_profiles WHERE case_id = %s", (case_id,)).fetchone()
        ) or {}
        express_interest = express_interest_payload(
            conn.execute(
                "SELECT * FROM express_interest_submissions WHERE case_id = %s", (case_id,)
            ).fetchone()
        )
        required_express_interest = [
            "legal_name",
            "fdic_certificate_number",
            "institution_type",
            "website",
        ]
        missing = [field for field in required_express_interest if not express_interest.get(field)]
        if not profile.get("additional_responses"):
            missing.append("institution_profile_responses")
        if missing:
            raise HTTPException(
                422,
                {
                    "message": "Express Interest data or required Institution Profile responses are incomplete.",
                    "missing": missing,
                },
            )
        now = utc_now()
        update_stage(conn, case_id, "DOCUMENTS", institution_profile_completed_at=now)
        return {"completed_at": now, "current_stage": "DOCUMENTS"}


@router.get("/{case_id}/documents")
async def get_documents(case_id: str):
    with connection() as conn:
        get_or_404(conn, case_id)
        rows = conn.execute(
            "SELECT * FROM documents WHERE case_id = %s ORDER BY created_at DESC",
            (case_id,),
        ).fetchall()
    # Hazel is the member-facing source of truth. Coverbase attachment metadata
    # recorded during explicit upload/retry is diagnostic only and never builds
    # or mutates this list.
    return [document_payload(row) for row in rows]


@router.post("/{case_id}/documents")
async def upload_document(case_id: str, file: UploadFile = File(...), document_type: str = Form(...)):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        require_at_least(case, "DOCUMENTS")
    original_name = Path(file.filename or "upload").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, "Upload a PDF, Word, or Excel file.")
    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File exceeds the 25 MB limit.")
    file_sha256 = hashlib.sha256(contents).hexdigest()
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(original_name).stem).strip("-") or "document"
    stored_name = f"{case_id}-{uuid4().hex}-{safe_stem}{suffix}"
    # The directory was created and write-probed at startup by ensure_upload_dir().
    (UPLOAD_DIR / stored_name).write_bytes(contents)
    try:
        with connection() as conn:
            backfill_case_document_hashes(conn, case_id)
            # RETURNING replaces cursor.lastrowid, which is a sqlite3-ism with no
            # psycopg equivalent. It also removes the follow-up SELECT.
            document = row_dict(
                conn.execute(
                    """INSERT INTO documents
                    (case_id, document_type, original_name, stored_name, size_bytes,
                     created_at, file_sha256) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING *""",
                    (case_id, document_type, original_name, stored_name, len(contents), utc_now(), file_sha256),
                ).fetchone()
            )
    except Exception:
        (UPLOAD_DIR / stored_name).unlink(missing_ok=True)
        raise
    return await sync_hazel_document(case, document, contents)


@router.post("/{case_id}/documents/{document_id}/coverbase-sync")
async def retry_document_coverbase_sync(case_id: str, document_id: int):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        require_at_least(case, "DOCUMENTS")
        document = row_dict(
            conn.execute(
                "SELECT * FROM documents WHERE id = %s AND case_id = %s",
                (document_id, case_id),
            ).fetchone()
        )
    if not document:
        raise HTTPException(404, "Document not found")
    return await sync_hazel_document(case, document)


@router.delete("/{case_id}/documents/{document_id}", status_code=204)
async def delete_document(case_id: str, document_id: int):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        row = conn.execute("SELECT * FROM documents WHERE id = %s AND case_id = %s", (document_id, case_id)).fetchone()
        if not row:
            raise HTTPException(404, "Document not found")
        conn.execute("DELETE FROM documents WHERE id = %s", (document_id,))
        remaining_reference = None
        if row["coverbase_document_id"]:
            remaining_reference = conn.execute(
                """SELECT id FROM documents WHERE case_id = %s
                AND coverbase_document_id = %s LIMIT 1""",
                (case_id, row["coverbase_document_id"]),
            ).fetchone()
    (UPLOAD_DIR / row["stored_name"]).unlink(missing_ok=True)
    if (
        row["coverbase_document_id"]
        and case.get("coverbase_session_id")
        and not remaining_reference
    ):
        try:
            await coverbase_service.unlink_intake_document(
                case["coverbase_session_id"], row["coverbase_document_id"]
            )
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            logger.warning(
                "[Coverbase] failed to unlink document %s after Hazel document %s was removed",
                row["coverbase_document_id"],
                document_id,
            )
            raise HTTPException(
                502,
                "The Hazel document was removed, but Coverbase session unlinking failed.",
            ) from exc


@router.post("/{case_id}/documents/complete")
def complete_documents(case_id: str):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        require_at_least(case, "DOCUMENTS")
        required = conn.execute(
            """SELECT coverbase_sync_status FROM documents
            WHERE case_id = %s AND document_type = 'bsa_policy'
            ORDER BY created_at DESC, id DESC LIMIT 1""",
            (case_id,),
        ).fetchone()
        if not required:
            raise HTTPException(422, "Upload the board-approved BSA/AML/OFAC policy before continuing.")
        if required["coverbase_sync_status"] != "synced":
            raise HTTPException(
                422,
                "The required BSA/AML/OFAC policy is stored in Hazel but must finish syncing to Coverbase before continuing.",
            )
        now = utc_now()
        update_stage(conn, case_id, "DUE_DILIGENCE", documents_completed_at=now)
        return {"completed_at": now, "current_stage": "DUE_DILIGENCE"}


@router.get("/{case_id}/due-diligence")
def get_due_diligence(case_id: str):
    with connection() as conn:
        get_or_404(conn, case_id)
        row = conn.execute("SELECT data_json, updated_at FROM due_diligence WHERE case_id = %s", (case_id,)).fetchone()
        # data_json is jsonb; psycopg returns it already parsed.
        return {"data": row["data_json"], "updated_at": row["updated_at"]}


@router.put("/{case_id}/due-diligence")
def save_due_diligence(case_id: str, payload: DueDiligenceUpdate):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        require_at_least(case, "DUE_DILIGENCE")
        now = utc_now()
        conn.execute("UPDATE due_diligence SET data_json = %s, updated_at = %s WHERE case_id = %s", (Jsonb(payload.data), now, case_id))
        return {"data": payload.data, "updated_at": now}


@router.post("/{case_id}/due-diligence/complete")
def complete_due_diligence(case_id: str):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        require_at_least(case, "DUE_DILIGENCE")
        now = utc_now()
        update_stage(conn, case_id, "RISK_QUESTIONS", due_diligence_completed_at=now)
        return {"completed_at": now, "current_stage": "RISK_QUESTIONS"}


@router.post("/{case_id}/coverbase/intake")
async def start_coverbase_intake(case_id: str):
    # Compatibility route for the existing Risk Questions UI. Session creation
    # now belongs to the post-NDA boundary and is idempotent.
    session = await ensure_coverbase_session(case_id)
    if session.get("reused"):
        return await coverbase_service.get_intake_session(session["session_id"])
    return session


@router.get("/{case_id}/coverbase/intake")
async def get_coverbase_intake(case_id: str):
    with connection() as conn:
        case = get_or_404(conn, case_id)
    if not case["coverbase_session_id"]:
        return {"status": "not_started", "items": []}
    try:
        return await coverbase_service.get_intake(case["coverbase_session_id"])
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(502, f"Coverbase intake could not be retrieved: {exc}") from exc


@router.get("/{case_id}/risk-questions")
async def get_risk_questions(case_id: str):
    with connection() as conn:
        case = get_or_404(conn, case_id)
    if not case["coverbase_session_id"]:
        raise HTTPException(
            409, "This case does not have a post-NDA Coverbase intake session."
        )
    try:
        return await coverbase_service.get_risk_questions(
            case["coverbase_session_id"]
        )
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(
            502, f"Coverbase Risk Questions could not be retrieved: {exc}"
        ) from exc


@router.post("/{case_id}/risk-questions/submit")
async def submit_risk_questions(case_id: str):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        if case["current_stage"] != "RISK_QUESTIONS":
            raise HTTPException(
                409, "Risk Questions cannot be edited after final submission."
            )
    if not case["coverbase_session_id"]:
        raise HTTPException(
            409, "This case does not have a post-NDA Coverbase intake session."
        )

    try:
        submitted = await coverbase_service.submit_risk_questions(
            case["coverbase_session_id"]
        )
    except CoverbaseQuestionnaireSavePending as exc:
        raise HTTPException(409, str(exc)) from exc
    except CoverbaseSubmissionValidationError as exc:
        raise HTTPException(
            422,
            {
                "message": str(exc),
                "error_code": exc.error_code,
                "missing_question_ids": exc.missing_question_ids,
            },
        ) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(
            502, f"Coverbase Risk Questions could not be submitted: {exc}"
        ) from exc

    coverbase_status = str(submitted.get("status") or "submitted")
    review_state, review_status = REVIEW_STATUS_MAP.get(
        coverbase_status, ("processing", "Processing / preparing for review")
    )
    submitted_at = case["risk_questions_submitted_at"] or utc_now()
    with connection() as conn:
        update_stage(
            conn,
            case_id,
            "HAZEL_REVIEW",
            risk_questions_submitted_at=submitted_at,
            coverbase_status=coverbase_status,
            coverbase_vendor_id=(
                submitted.get("vendor_id") or case["coverbase_vendor_id"]
            ),
            hazel_review_status=review_state,
            review_status=review_status,
        )
    logger.info(
        "[Hazel] Risk Questions submitted for case %s; Coverbase status %s",
        case_id,
        coverbase_status,
    )
    return {
        "current_stage": "HAZEL_REVIEW",
        "risk_questions_submitted_at": submitted_at,
        "coverbase_session_id": case["coverbase_session_id"],
        "coverbase_status": coverbase_status,
        "hazel_review_status": review_state,
        "esign_eligible": coverbase_status == "accepted",
    }


async def build_hazel_review_payload(case_id: str):
    """Combine read-only Coverbase status with Hazel-owned review requests."""
    with connection() as conn:
        case = get_or_404(conn, case_id)
        require_at_least(case, "HAZEL_REVIEW")
    coverbase_status = str(case.get("coverbase_status") or "unknown")
    coverbase_vendor_id = case.get("coverbase_vendor_id")
    status_sync_error = None
    if case.get("coverbase_session_id"):
        try:
            review = await coverbase_service.get_review_status(
                case["coverbase_session_id"]
            )
            coverbase_status = str(review.get("status") or coverbase_status)
            coverbase_vendor_id = review.get("vendor_id") or coverbase_vendor_id
        except (httpx.HTTPError, RuntimeError) as exc:
            status_sync_error = (
                "Coverbase status is temporarily unavailable; Hazel is showing "
                "the most recently stored review status."
            )
            logger.warning(
                "[Coverbase] Hazel Review status unavailable for session %s: %s",
                case["coverbase_session_id"],
                exc,
            )

    with connection() as conn:
        clarifications = load_review_clarifications(conn, case_id)
    current_clarification = next(
        (
            clarification
            for clarification in clarifications
            if clarification["status"] in UNRESOLVED_STATUSES
        ),
        None,
    )
    review_state = review_state_for(coverbase_status, current_clarification)
    review_status = {
        "approved": "Review complete",
        "rejected": "Rejected",
        "partial": "Needs explicit handling",
        "action_required": "Action required — additional information requested",
        "response_submitted": "Response submitted · review resumed",
        "under_review": REVIEW_STATUS_MAP.get(
            coverbase_status, ("under_review", "Under Hazel/Vantage review")
        )[1],
    }[review_state]
    changed = (
        coverbase_status != case["coverbase_status"]
        or review_state != case["hazel_review_status"]
        or coverbase_vendor_id != case["coverbase_vendor_id"]
    )
    with connection() as conn:
        conn.execute(
            """UPDATE onboarding_cases
            SET coverbase_status = %s, coverbase_vendor_id = %s,
                hazel_review_status = %s, review_status = %s,
                additional_information_required = %s,
                updated_at = %s
            WHERE id = %s""",
            (
                coverbase_status,
                coverbase_vendor_id,
                review_state,
                review_status,
                review_state == "action_required",  # boolean column, no int() cast
                utc_now() if changed else case["updated_at"],
                case_id,
            ),
        )
    return {
        "coverbase_session_id": case["coverbase_session_id"],
        "coverbase_status": coverbase_status,
        "review_state": review_state,
        "hazel_review_status": review_state,
        "review_status": review_status,
        "current_stage": case["current_stage"],
        "risk_questions_submitted_at": case["risk_questions_submitted_at"],
        "esign_eligible": coverbase_status == "accepted",
        "open_clarification": (
            current_clarification
            if review_state == "action_required" and current_clarification
            else None
        ),
        "current_clarification": current_clarification,
        "clarification_history": clarifications,
        "history_events": clarification_history_events(current_clarification),
        "coverbase_sync_status": (
            current_clarification["coverbase_sync_status"]
            if current_clarification
            else None
        ),
        "coverbase_status_sync_error": status_sync_error,
        "clarification_integration": "hazel_local",
        "coverbase_clarification_sync_supported": False,
    }


@router.get("/{case_id}/hazel-review")
async def get_hazel_review(case_id: str):
    return await build_hazel_review_payload(case_id)


@router.get("/{case_id}/hazel-review/status")
async def get_hazel_review_status(case_id: str):
    """Compatibility alias for the original Hazel Review polling endpoint."""
    return await build_hazel_review_payload(case_id)


@router.post("/{case_id}/hazel-review/clarifications/{clarification_id}/draft")
def save_clarification_draft(
    case_id: str, clarification_id: str, payload: ClarificationDraftUpdate
):
    now = utc_now()
    with connection() as conn:
        case = get_or_404(conn, case_id)
        require_at_least(case, "HAZEL_REVIEW")
        if case["coverbase_status"] in {"accepted", "rejected"}:
            raise HTTPException(409, "The Coverbase review decision is already final.")
        clarification = conn.execute(
            "SELECT * FROM review_clarifications WHERE id = %s AND case_id = %s",
            (clarification_id, case_id),
        ).fetchone()
        if not clarification:
            raise HTTPException(404, "Hazel review clarification not found")
        if clarification["status"] not in ACTION_REQUIRED_STATUSES:
            raise HTTPException(409, "This clarification can no longer be edited.")
        conn.execute(
            """UPDATE review_clarifications SET member_response = %s,
            status = 'draft', updated_at = %s WHERE id = %s""",
            (payload.response, now, clarification_id),
        )
        conn.execute(
            """UPDATE onboarding_cases SET additional_information_required = true,
            hazel_review_status = 'action_required',
            review_status = 'Action required — additional information requested',
            updated_at = %s WHERE id = %s""",
            (now, case_id),
        )
        saved = conn.execute(
            "SELECT * FROM review_clarifications WHERE id = %s", (clarification_id,)
        ).fetchone()
        uploaded = (
            conn.execute(
                "SELECT * FROM documents WHERE id = %s",
                (saved["uploaded_hazel_document_id"],),
            ).fetchone()
            if saved["uploaded_hazel_document_id"] is not None
            else None
        )
    return clarification_payload(saved, document_payload(uploaded) if uploaded else None)


@router.post("/{case_id}/hazel-review/clarifications/{clarification_id}/document")
async def upload_clarification_document(
    case_id: str, clarification_id: str, file: UploadFile = File(...)
):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        require_at_least(case, "HAZEL_REVIEW")
        clarification = conn.execute(
            "SELECT * FROM review_clarifications WHERE id = %s AND case_id = %s",
            (clarification_id, case_id),
        ).fetchone()
        if not clarification:
            raise HTTPException(404, "Hazel review clarification not found")
        if clarification["status"] not in ACTION_REQUIRED_STATUSES:
            raise HTTPException(409, "This clarification can no longer receive documents.")
        if case["coverbase_status"] in {"accepted", "rejected"}:
            raise HTTPException(409, "The Coverbase review decision is already final.")

    # Reuse Hazel's existing local-first upload and supported Coverbase document
    # synchronization. No clarification email/activity API is called here.
    document = await upload_document(case_id, file, "clarification")
    now = utc_now()
    with connection() as conn:
        conn.execute(
            """UPDATE review_clarifications SET uploaded_hazel_document_id = %s,
            status = 'draft', updated_at = %s WHERE id = %s AND case_id = %s""",
            (document["id"], now, clarification_id, case_id),
        )
        conn.execute(
            """UPDATE onboarding_cases SET additional_information_required = true,
            hazel_review_status = 'action_required',
            review_status = 'Action required — additional information requested',
            updated_at = %s WHERE id = %s""",
            (now, case_id),
        )
        updated = conn.execute(
            "SELECT * FROM review_clarifications WHERE id = %s", (clarification_id,)
        ).fetchone()
    return {
        "clarification": clarification_payload(updated, document),
        "document": document,
    }


@router.post("/{case_id}/hazel-review/clarifications/{clarification_id}/submit")
def submit_clarification_response(case_id: str, clarification_id: str):
    now = utc_now()
    with connection() as conn:
        case = get_or_404(conn, case_id)
        require_at_least(case, "HAZEL_REVIEW")
        if case["coverbase_status"] in {"accepted", "rejected"}:
            raise HTTPException(409, "The Coverbase review decision is already final.")
        clarification = conn.execute(
            "SELECT * FROM review_clarifications WHERE id = %s AND case_id = %s",
            (clarification_id, case_id),
        ).fetchone()
        if not clarification:
            raise HTTPException(404, "Hazel review clarification not found")
        if clarification["status"] not in ACTION_REQUIRED_STATUSES:
            raise HTTPException(409, "This clarification has already been submitted.")
        if not clarification["member_response"].strip():
            raise HTTPException(422, "Add and save a response before submitting.")
        if (
            clarification["document_required"]
            and clarification["uploaded_hazel_document_id"] is None
        ):
            raise HTTPException(422, "Upload the requested document before submitting.")
        conn.execute(
            """UPDATE review_clarifications SET status = 'submitted',
            submitted_at = %s, coverbase_sync_status = 'pending_integration',
            updated_at = %s WHERE id = %s""",
            (now, now, clarification_id),
        )
        conn.execute(
            """UPDATE onboarding_cases SET additional_information_required = false,
            hazel_review_status = 'response_submitted',
            review_status = 'Response submitted · review resumed',
            updated_at = %s WHERE id = %s""",
            (now, case_id),
        )
        submitted = conn.execute(
            "SELECT * FROM review_clarifications WHERE id = %s", (clarification_id,)
        ).fetchone()
        uploaded = (
            conn.execute(
                "SELECT * FROM documents WHERE id = %s",
                (submitted["uploaded_hazel_document_id"],),
            ).fetchone()
            if submitted["uploaded_hazel_document_id"] is not None
            else None
        )
    logger.info(
        "[Hazel] saved clarification response %s for case %s; Coverbase sync pending integration",
        clarification_id,
        case_id,
    )
    return {
        "clarification": clarification_payload(
            submitted, document_payload(uploaded) if uploaded else None
        ),
        "review_state": "response_submitted",
        "coverbase_sync_status": "pending_integration",
    }


@router.post("/{case_id}/risk-questions/{question_id}")
async def save_risk_answer(
    case_id: str, question_id: str, payload: RiskQuestionResponseUpdate
):
    with connection() as conn:
        case = get_or_404(conn, case_id)
        if case["current_stage"] != "RISK_QUESTIONS":
            raise HTTPException(
                409, "Risk Questions cannot be edited after final submission."
            )
    if not case["coverbase_session_id"]:
        raise HTTPException(
            409, "This case does not have a post-NDA Coverbase intake session."
        )
    try:
        return await coverbase_service.update_risk_question_response(
            case["coverbase_session_id"],
            question_id,
            payload.model_dump(),
            payload.model_fields_set,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(
            502, f"Coverbase Risk Question could not be saved: {exc}"
        ) from exc
