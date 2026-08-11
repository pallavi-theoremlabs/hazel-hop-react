from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
from typing import Any
from urllib.parse import urljoin

import httpx

from app.config import settings

logger = logging.getLogger("uvicorn.error")

AUTH_TEST_PATH = "/v1/utils/authtest"
QUESTIONNAIRES_PATH = "/v1/intake/api/questionnaires"
INTAKE_SESSIONS_PATH = "/v1/intake/api/sessions"
INTAKE_SESSION_PATH = "/v1/intake_session"
PRIMARY_CONTACT_QUESTION_ID = "cbqn_21693e24daba420ab628170a93f088d1"
HAZEL_USE_CASE_CONCEPTS = (
    "commercial banking",
    "business banking",
    "banking",
    "payment processing",
    "treasury",
    "business checking",
    "cash management",
    "financial services",
    "business lending",
    "commercial lending",
    "lending",
    "deposit",
    "merchant services",
    "wealth management",
)
PROFILE_GENERATION_POLL_ATTEMPTS = 20
PROFILE_GENERATION_POLL_SECONDS = 2
QUESTIONNAIRE_PROCESSING_POLL_ATTEMPTS = 10
QUESTIONNAIRE_PROCESSING_POLL_SECONDS = 1


class InstitutionProfileQuestionsEmpty(RuntimeError):
    """Coverbase session exists but Step 2 questions have not been generated yet."""


class CoverbaseSubmissionValidationError(RuntimeError):
    """Coverbase or Hazel found required questionnaire responses missing."""

    def __init__(self, message: str, missing_question_ids: list[str] | None = None):
        super().__init__(message)
        self.error_code = "missing_required_questions"
        self.missing_question_ids = missing_question_ids or []


class CoverbaseQuestionnaireSavePending(RuntimeError):
    """Final submission was attempted while a response write was still active."""


class CoverbaseDocumentSyncError(RuntimeError):
    """Document synchronization failed after one or more completed steps."""

    def __init__(self, message: str, result: dict[str, Any]):
        super().__init__(message)
        self.result = copy.deepcopy(result)

MOCK_QUESTIONS = [
    {
        "question_id": "rq-001",
        "question_text": "Does the institution maintain a board-approved BSA/AML/OFAC compliance program?",
        "response_type": "single_select",
        "answer_text": "Yes",
        "selected_options": ["Yes"],
        "reasoning": "The uploaded policy is identified as board-approved and describes the institution's BSA, AML, and OFAC program.",
        "status": "answered",
    },
    {
        "question_id": "rq-002",
        "question_text": "Will the institution use the Hazel Network to support fintech or banking-as-a-service programs?",
        "response_type": "single_select",
        "answer_text": "No",
        "selected_options": ["No"],
        "reasoning": "The institution profile states that no fintech partnership or BaaS program is planned for this use case.",
        "status": "answered",
    },
    {
        "question_id": "rq-003",
        "question_text": "Describe the institution's intended use of the Hazel Network.",
        "response_type": "free_text",
        "answer_text": "Domestic network settlement and reporting for member-bank activity.",
        "selected_options": [],
        "reasoning": "This response combines the profile's domestic activity selection with the due diligence use-case summary.",
        "status": "answered",
    },
    {
        "question_id": "rq-004",
        "question_text": "Does the institution maintain correspondent banking relationships outside the United States?",
        "response_type": "single_select",
        "answer_text": "No",
        "selected_options": ["No"],
        "reasoning": "The institution profile indicates no international correspondent relationships.",
        "status": "answered",
    },
]


class CoverbaseService:
    """Server-side adapter for Coverbase APIs used by Hazel onboarding."""

    def __init__(self):
        self.mode = settings.coverbase_mode
        self.base_url = settings.coverbase_base_url
        self.api_key = settings.coverbase_api_key
        self.questionnaire_id = settings.coverbase_questionnaire_id
        self._mock_selected_use_cases: dict[str, str] = {}
        self._mock_document_ids: dict[str, list[str]] = {}
        self._mock_documents: dict[str, dict[str, Any]] = {}
        self._mock_session_statuses: dict[str, str] = {}
        self._mock_questionnaire_response_overrides: dict[
            str, list[dict[str, Any]]
        ] = {}
        self._pending_questionnaire_saves: dict[str, int] = {}

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("COVERBASE_API_KEY is required when COVERBASE_MODE=live")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def test_connection(self) -> dict[str, Any]:
        """Verify credentials through Coverbase's documented auth-test endpoint."""
        if self.mode == "mock":
            return {"connected": True, "mode": "mock", "endpoint_called": None}
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=30.0, headers=self._headers()
        ) as client:
            response = await client.get(AUTH_TEST_PATH)
            response.raise_for_status()
            return response.json()

    async def get_questionnaires(self, questionnaire_type: str | None = None) -> dict[str, Any]:
        """List questionnaires through the documented intake API."""
        if self.mode == "mock":
            items = []
            if self.questionnaire_id:
                items.append(
                    {
                        "id": self.questionnaire_id,
                        "name": "Configured mock questionnaire",
                        "description": "Local Hazel mock-mode questionnaire.",
                        "type": questionnaire_type or "irq",
                    }
                )
            return {"items": items, "total": len(items), "mode": "mock"}
        params = {"type": questionnaire_type} if questionnaire_type else None
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=30.0, headers=self._headers()
        ) as client:
            response = await client.get(QUESTIONNAIRES_PATH, params=params)
            response.raise_for_status()
            return response.json()

    async def create_intake_session(
        self, case_id: str, profile: dict[str, Any], due_diligence: dict[str, Any]
    ) -> dict[str, Any]:
        """Create an intake session after the private HOP NDA boundary."""
        logger.info("[Coverbase] creating intake session")
        if not self.questionnaire_id:
            raise RuntimeError("COVERBASE_QUESTIONNAIRE_ID is required to create an intake session")
        if not profile.get("legal_name"):
            raise RuntimeError("Hazel Express Interest legal name is required to create an intake session")
        payload = {
            "vendor_name": profile["legal_name"],
            "vendor_website": profile.get("website") or "",
            "vendor_description": profile.get("institution_type") or "Financial institution",
            "use_case": "Hazel Network member bank onboarding",
            "questionnaire_ids": [self.questionnaire_id],
            "external_id": case_id,
            "context": self.build_context(profile, due_diligence),
        }
        if self.mode == "mock":
            session_id = f"mock-{case_id.lower()}"
            self._mock_selected_use_cases.pop(session_id, None)
            self._mock_questionnaire_response_overrides.pop(session_id, None)
            self._mock_session_statuses[session_id] = "open"
            return {
                "session_id": session_id,
                "status": "open",
                "vendor_id": "mock-northstar",
                "items": MOCK_QUESTIONS,
                "request": payload,
            }
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=60.0, headers=self._headers()
        ) as client:
            response = await client.post(INTAKE_SESSIONS_PATH, json=payload)
            response.raise_for_status()
            return response.json()

    async def get_intake_session(self, session_id: str) -> dict[str, Any]:
        """Retrieve an intake session through the documented intake API."""
        if self.mode == "mock":
            return {
                "session_id": session_id,
                "status": "complete",
                "vendor_id": "mock-northstar",
                "items": MOCK_QUESTIONS,
            }
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=60.0, headers=self._headers()
        ) as client:
            response = await client.get(f"{INTAKE_SESSIONS_PATH}/{session_id}")
            response.raise_for_status()
            return response.json()

    async def get_institution_profile_questions(self, session_id: str) -> dict[str, Any]:
        """Load Step 2 questions from session_data.ai_generated_followups only."""
        path = f"{INTAKE_SESSION_PATH}/{session_id}"
        logger.info("[Coverbase] loading Institution Profile questions")
        logger.info("[Coverbase] GET %s", path)
        coverbase_response = await self._get_portal_intake_session(session_id)

        session_data = coverbase_response.get("session_data")
        if not isinstance(session_data, dict):
            raise RuntimeError("Coverbase response did not include session_data")
        ai_followups = session_data.get("ai_generated_followups") or []
        user_followups = session_data.get("user_input_followups") or []
        if not isinstance(ai_followups, list):
            raise RuntimeError("Coverbase ai_generated_followups was not a list")
        ignored_count = len(user_followups) if isinstance(user_followups, list) else 0
        logger.info("[Coverbase] loaded %s ai_generated_followups", len(ai_followups))
        logger.info("[Coverbase] ignored %s user_input_followups", ignored_count)
        if not ai_followups:
            raise InstitutionProfileQuestionsEmpty(
                "Coverbase ai_generated_followups is still empty"
            )
        return self.institution_profile_schema(ai_followups)

    async def _get_portal_intake_session(self, session_id: str) -> dict[str, Any]:
        """Load the intake state used by Coverbase's public intake workflow."""
        if self.mode == "mock":
            followups = self._mock_ai_generated_followups(session_id)
            logger.info("[Coverbase] response status 200")
            return {
                "id": session_id,
                "status": self._mock_session_statuses.get(session_id, "open"),
                "vendor_id": "mock-northstar",
                "session_data": {
                    "use_case": {
                        "question": None,
                        "options": [
                            "Commercial banking services",
                            "Retail deposit products",
                            "Business lending solutions",
                        ],
                        "response": self._mock_selected_use_cases.get(session_id),
                    },
                    "ai_generated_followups": followups,
                    "user_input_followups": [
                        {"question": "Who is the primary Hazel relationship contact?"}
                    ],
                    "document_ids": self._mock_document_ids.get(session_id, []),
                    "is_processing_questions": False,
                    "questionnaire_responses": copy.deepcopy(
                        self._mock_questionnaire_response_overrides.get(session_id)
                        or self._mock_questionnaire_responses()
                    ),
                },
            }
        path = f"{INTAKE_SESSION_PATH}/{session_id}"
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=60.0, headers=self._headers()
        ) as client:
            response = await client.get(path)
            logger.info("[Coverbase] response status %s", response.status_code)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Coverbase intake session response was not an object")
        return data

    async def sync_intake_document(
        self,
        session_id: str,
        filename: str,
        file_bytes: bytes,
        extension: str,
    ) -> dict[str, Any]:
        """Upload and attach a Hazel file through Coverbase's isolated portal adapter."""
        extension = extension.lstrip(".").lower()
        result: dict[str, Any] = {
            "coverbase_document_id": None,
            "signed_upload_request_status": None,
            "s3_upload_status": None,
            "document_registration_status": None,
            "session_attachment_status": None,
            "metadata_status": None,
            "document_in_session": False,
            "duplicate_upload_prevented": False,
        }
        logger.info(
            "[Coverbase] requesting signed document upload for session %s", session_id
        )

        if self.mode == "mock":
            digest = hashlib.sha256(
                session_id.encode("utf-8") + filename.encode("utf-8") + file_bytes
            ).hexdigest()[:24]
            document_id = f"mock-document-{digest}"
            self._mock_documents[document_id] = {
                "id": document_id,
                "name": filename,
                "size": len(file_bytes),
                "extension": extension,
            }
            result.update(
                {
                    "coverbase_document_id": document_id,
                    "signed_upload_request_status": 200,
                    "s3_upload_status": 204,
                    "document_registration_status": 201,
                }
            )
            attachment = await self.attach_intake_document(session_id, document_id)
            return {**result, **attachment, "duplicate_upload_prevented": False}

        signed_path = (
            f"{INTAKE_SESSION_PATH}/{session_id}/file/uploadable_url"
        )
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=60.0, headers=self._headers()
            ) as client:
                signed_response = await client.get(
                    signed_path, params={"extension": extension}
                )
                result["signed_upload_request_status"] = signed_response.status_code
                signed_response.raise_for_status()
                signed = signed_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "[Coverbase] signed upload request failed for session %s", session_id
            )
            raise CoverbaseDocumentSyncError(
                "Coverbase signed-upload request failed", result
            ) from exc

        if not isinstance(signed, dict):
            raise CoverbaseDocumentSyncError(
                "Coverbase signed-upload response was not an object", result
            )
        upload_url = signed.get("url")
        raw_fields = signed.get("fields")
        if not isinstance(upload_url, str) or not isinstance(raw_fields, dict):
            raise CoverbaseDocumentSyncError(
                "Coverbase signed-upload response was incomplete", result
            )
        fields = {str(key): str(value) for key, value in raw_fields.items()}
        object_key = fields.get("key")
        if not object_key:
            raise CoverbaseDocumentSyncError(
                "Coverbase signed-upload response did not include an object key", result
            )

        try:
            # Deliberately use a separate client with no Coverbase authorization
            # headers. The signed form fields authorize this storage request.
            async with httpx.AsyncClient(timeout=120.0) as storage_client:
                storage_response = await storage_client.post(
                    upload_url,
                    data=fields,
                    files={
                        "file": (
                            filename,
                            file_bytes,
                            fields.get("Content-Type") or "application/octet-stream",
                        )
                    },
                )
                result["s3_upload_status"] = storage_response.status_code
                storage_response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning(
                "[Coverbase] signed storage upload failed for session %s", session_id
            )
            raise CoverbaseDocumentSyncError(
                "Coverbase storage upload failed", result
            ) from exc

        registration_path = f"{INTAKE_SESSION_PATH}/{session_id}/document"
        registration_payload = {
            "name": filename,
            "size": len(file_bytes),
            "s3_url": urljoin(f"{upload_url.rstrip('/')}/", object_key.lstrip("/")),
            "extension": extension,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=60.0, headers=self._headers()
            ) as client:
                registration_response = await client.post(
                    registration_path, json=registration_payload
                )
                result["document_registration_status"] = (
                    registration_response.status_code
                )
                registration_response.raise_for_status()
                document = registration_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "[Coverbase] document registration failed for session %s", session_id
            )
            raise CoverbaseDocumentSyncError(
                "Coverbase document registration failed", result
            ) from exc

        document_id = document.get("id") if isinstance(document, dict) else None
        if not document_id:
            raise CoverbaseDocumentSyncError(
                "Coverbase document registration did not return a document ID", result
            )
        result["coverbase_document_id"] = str(document_id)
        logger.info(
            "[Coverbase] registered intake document %s for session %s",
            document_id,
            session_id,
        )

        try:
            attachment = await self.attach_intake_document(
                session_id, str(document_id)
            )
        except CoverbaseDocumentSyncError as exc:
            raise CoverbaseDocumentSyncError(
                str(exc),
                {**result, **exc.result, "duplicate_upload_prevented": False},
            ) from exc
        return {**result, **attachment, "duplicate_upload_prevented": False}

    async def attach_intake_document(
        self, session_id: str, document_id: str
    ) -> dict[str, Any]:
        """Attach an already registered document without uploading it again."""
        result: dict[str, Any] = {
            "coverbase_document_id": document_id,
            "session_attachment_status": None,
            "metadata_status": None,
            "document_in_session": False,
            "duplicate_upload_prevented": True,
        }
        try:
            session = await self._get_portal_intake_session(session_id)
            session_data = session.get("session_data")
            if not isinstance(session_data, dict):
                raise RuntimeError("Coverbase response did not include session_data")
            current_ids = session_data.get("document_ids") or []
            if not isinstance(current_ids, list):
                raise RuntimeError("Coverbase session_data.document_ids was not a list")
            current_ids = [str(value) for value in current_ids]
            unique_ids = list(dict.fromkeys(current_ids))
            updated_ids = unique_ids if document_id in unique_ids else unique_ids + [document_id]
            result["session_document_ids_before"] = current_ids
            result["session_document_ids_after"] = updated_ids
            if updated_ids == current_ids:
                result["session_attachment_status"] = 200
                result["document_in_session"] = True
            elif self.mode == "mock":
                self._mock_document_ids[session_id] = updated_ids
                result["session_attachment_status"] = 200
                result["document_in_session"] = True
            else:
                path = f"{INTAKE_SESSION_PATH}/{session_id}"
                updated_session_data = copy.deepcopy(session_data)
                updated_session_data["document_ids"] = updated_ids
                async with httpx.AsyncClient(
                    base_url=self.base_url, timeout=60.0, headers=self._headers()
                ) as client:
                    response = await client.post(
                        path,
                        json={"session_data": updated_session_data},
                    )
                    result["session_attachment_status"] = response.status_code
                    response.raise_for_status()
                result["document_in_session"] = True
            metadata = await self.get_intake_document(session_id, document_id)
            result["metadata_status"] = metadata["status"]
            result["metadata_filename"] = metadata["document"].get("name")
            logger.info(
                "[Coverbase] attached intake document %s to session %s",
                document_id,
                session_id,
            )
            return result
        except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
            logger.warning(
                "[Coverbase] document attachment verification failed for session %s",
                session_id,
            )
            raise CoverbaseDocumentSyncError(
                "Coverbase document attachment or verification failed", result
            ) from exc

    async def unlink_intake_document(
        self, session_id: str, document_id: str
    ) -> dict[str, Any]:
        """Remove a document ID from a session without deleting the remote object."""
        session = await self._get_portal_intake_session(session_id)
        session_data = session.get("session_data")
        if not isinstance(session_data, dict):
            raise RuntimeError("Coverbase response did not include session_data")
        current_ids = session_data.get("document_ids") or []
        if not isinstance(current_ids, list):
            raise RuntimeError("Coverbase session_data.document_ids was not a list")
        current_ids = [str(value) for value in current_ids]
        updated_ids = [value for value in current_ids if value != document_id]
        result = {
            "coverbase_document_id": document_id,
            "session_document_ids_before": current_ids,
            "session_document_ids_after": updated_ids,
            "session_unlink_status": 200,
            "document_unlinked": document_id in current_ids,
            "remote_document_deleted": False,
        }
        if updated_ids == current_ids:
            return result
        if self.mode == "mock":
            self._mock_document_ids[session_id] = updated_ids
        else:
            path = f"{INTAKE_SESSION_PATH}/{session_id}"
            updated_session_data = copy.deepcopy(session_data)
            updated_session_data["document_ids"] = updated_ids
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=60.0, headers=self._headers()
            ) as client:
                response = await client.post(
                    path, json={"session_data": updated_session_data}
                )
                result["session_unlink_status"] = response.status_code
                response.raise_for_status()
        logger.info(
            "[Coverbase] unlinked document %s from session %s without hard delete",
            document_id,
            session_id,
        )
        return result

    async def get_intake_document(
        self, session_id: str, document_id: str
    ) -> dict[str, Any]:
        """Retrieve session document metadata without exposing download credentials."""
        if self.mode == "mock":
            document = self._mock_documents.get(document_id)
            if not document:
                raise RuntimeError("Mock Coverbase document was not found")
            return {"status": 200, "document": copy.deepcopy(document)}
        path = f"{INTAKE_SESSION_PATH}/{session_id}/document/{document_id}"
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=60.0, headers=self._headers()
        ) as client:
            response = await client.get(path)
            response.raise_for_status()
            document = response.json()
        if not isinstance(document, dict):
            raise RuntimeError("Coverbase document metadata was not an object")
        return {"status": response.status_code, "document": document}

    async def get_intake_document_ids(self, session_id: str) -> list[str]:
        """Read the current session attachment list for Hazel debug status."""
        session = await self._get_portal_intake_session(session_id)
        session_data = session.get("session_data")
        if not isinstance(session_data, dict):
            raise RuntimeError("Coverbase response did not include session_data")
        document_ids = session_data.get("document_ids") or []
        if not isinstance(document_ids, list):
            raise RuntimeError("Coverbase session_data.document_ids was not a list")
        return [str(value) for value in document_ids]

    def _mock_ai_generated_followups(self, session_id: str) -> list[dict[str, Any]]:
        if session_id not in self._mock_selected_use_cases:
            return []
        return [
            {
                "question": "Is your institution a bank, credit union, or other type of financial institution?",
                "options": [
                    "Bank (FDIC insured)",
                    "Credit union (NCUA insured)",
                    "Other financial institution",
                ],
                "response": None,
                "question_id": None,
                "response_type": "select_one",
            },
            {
                "question": "Does your institution maintain correspondent relationships outside the United States?",
                "options": ["Yes", "No", "Unsure"],
                "response": None,
                "question_id": None,
                "response_type": "select_one",
            },
        ]

    def _mock_questionnaire_responses(self) -> list[dict[str, Any]]:
        questionnaire_id = self.questionnaire_id or "mock-irq-questionnaire"
        responses = []
        for question in MOCK_QUESTIONS:
            selected_labels = question.get("selected_options") or []
            responses.append(
                {
                    "question_id": question["question_id"],
                    "questionnaire_id": questionnaire_id,
                    "question_text": question["question_text"],
                    "response_type": question["response_type"],
                    "response": question.get("answer_text") or "",
                    "selected_option_ids": [
                        self._mock_option_id(question["question_id"], label)
                        for label in selected_labels
                    ],
                    "response_data": None,
                    "reviewed": True,
                    "is_ai_generated": True,
                    "detailed_reasoning": question.get("reasoning"),
                }
            )
        return responses

    @staticmethod
    def _mock_option_id(question_id: str, label: str) -> str:
        digest = hashlib.sha256(f"{question_id}:{label}".encode("utf-8")).hexdigest()
        return f"mock-option-{digest[:16]}"

    def _mock_questionnaire_metadata(self, questionnaire_id: str) -> dict[str, Any]:
        section_id = "mock-risk-section"
        questions = []
        for index, question in enumerate(MOCK_QUESTIONS):
            labels = question.get("selected_options") or []
            if question["response_type"] in {"single_select", "select_one"}:
                labels = list(dict.fromkeys([*labels, "Yes", "No", "Unsure"]))
            questions.append(
                {
                    "id": question["question_id"],
                    "section_id": section_id,
                    "sort_order": index,
                    "is_required": True,
                    "user_review_required": True,
                    "options": [
                        {
                            "id": self._mock_option_id(question["question_id"], label),
                            "name": label,
                        }
                        for label in labels
                    ],
                }
            )
        return {
            "id": questionnaire_id,
            "sections": [
                {"id": section_id, "name": "Risk Questions", "sort_order": 0}
            ],
            "questions": questions,
        }

    async def generate_institution_profile_questions(
        self, session_id: str, institution_name: str
    ) -> dict[str, Any]:
        """Run Step 1 enrichment, then poll until Step 2 follow-ups are available."""
        path = (
            f"{INTAKE_SESSION_PATH}/{session_id}"
            "/actions/get_vendor_info_and_use_cases"
        )
        payload = {
            "vendor_search_input": institution_name,
            "get_use_cases": True,
            "get_product_services": False,
        }
        logger.info("[Coverbase] generating vendor info and use cases")
        logger.info("[Coverbase] endpoint called POST %s", path)
        logger.info("[Coverbase] session id %s", session_id)
        if self.mode == "mock":
            logger.info("[Coverbase] response status 200")
            enriched_session = await self._get_portal_intake_session(session_id)
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=60.0, headers=self._headers()
            ) as client:
                response = await client.post(path, json=payload)
                logger.info("[Coverbase] response status %s", response.status_code)
                response.raise_for_status()
                enriched_session = response.json()
            if not isinstance(enriched_session, dict):
                raise RuntimeError("Coverbase enrichment response was not an object")

        await self.complete_intake_step_one(session_id, enriched_session)

        for attempt in range(PROFILE_GENERATION_POLL_ATTEMPTS):
            if attempt:
                await asyncio.sleep(PROFILE_GENERATION_POLL_SECONDS)
            try:
                schema = await self.get_institution_profile_questions(session_id)
                question_count = sum(
                    len(section.get("questions", [])) for section in schema.get("sections", [])
                )
                logger.info("[Coverbase] generated %s follow-up questions", question_count)
                return schema
            except InstitutionProfileQuestionsEmpty:
                continue
        logger.info("[Coverbase] generated 0 follow-up questions")
        raise InstitutionProfileQuestionsEmpty(
            "Coverbase did not generate ai_generated_followups before the polling timeout"
        )

    async def complete_intake_step_one(
        self, session_id: str, enriched_session: dict[str, Any]
    ) -> None:
        """Mirror Coverbase's Select Vendor -> Additional Information transition."""
        session_data = enriched_session.get("session_data")
        if not isinstance(session_data, dict):
            enriched_session = await self._get_portal_intake_session(session_id)
            session_data = enriched_session.get("session_data")
        if not isinstance(session_data, dict):
            raise RuntimeError("Coverbase enrichment did not return session_data")

        use_case = session_data.get("use_case")
        if not isinstance(use_case, dict):
            raise RuntimeError("Coverbase enrichment did not return Step 1 use-case options")
        raw_options = use_case.get("options") or []
        options = [str(option) for option in raw_options if isinstance(option, str)]
        logger.info("[Coverbase] available use cases: %s", options)

        selected_use_case = self.select_hazel_use_case(options)

        update_path = f"{INTAKE_SESSION_PATH}/{session_id}"
        completion_path = (
            f"{INTAKE_SESSION_PATH}/{session_id}/actions/process_follow_up_questions"
        )
        update_payload = {
            "session_data": {
                "use_case": {
                    "options": options,
                    "response": selected_use_case,
                }
            }
        }
        logger.info("[Coverbase] selected use case: %s", selected_use_case)
        logger.info("[Coverbase] endpoint used to save Step 1 POST %s", update_path)

        if self.mode == "mock":
            logger.info("[Coverbase] Step 1 save response status 200")
            logger.info("[Coverbase] updated Step 1 use case response")
            logger.info(
                "[Coverbase] endpoint used to complete Step 1 POST %s?is_supplier_flow=false",
                completion_path,
            )
            logger.info("[Coverbase] triggering process_follow_up_questions")
            self._mock_selected_use_cases[session_id] = selected_use_case
            logger.info("[Coverbase] follow-up processing response status 200")
            return

        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=60.0, headers=self._headers()
        ) as client:
            update_response = await client.post(update_path, json=update_payload)
            logger.info(
                "[Coverbase] Step 1 save response status %s",
                update_response.status_code,
            )
            update_response.raise_for_status()
            logger.info("[Coverbase] updated Step 1 use case response")
            logger.info(
                "[Coverbase] endpoint used to complete Step 1 POST %s?is_supplier_flow=false",
                completion_path,
            )
            logger.info("[Coverbase] triggering process_follow_up_questions")
            completion_response = await client.post(
                completion_path,
                params={"is_supplier_flow": False},
            )
            logger.info(
                "[Coverbase] follow-up processing response status %s",
                completion_response.status_code,
            )
            completion_response.raise_for_status()

    async def sync_institution_profile_responses(
        self,
        session_id: str,
        hazel_responses: dict[str, Any],
        submit_interest: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist Hazel Step 2 answers, then start Coverbase questionnaire processing."""
        logger.info("[Coverbase] loading Step 2 session responses")
        intake_session = await self._get_portal_intake_session(session_id)
        session_data = intake_session.get("session_data")
        if not isinstance(session_data, dict):
            raise RuntimeError("Coverbase response did not include session_data")
        existing_followups = session_data.get("ai_generated_followups")
        if not isinstance(existing_followups, list) or not existing_followups:
            raise RuntimeError("Coverbase session did not include ai_generated_followups")
        existing_user_followups = session_data.get("user_input_followups")
        if not isinstance(existing_user_followups, list):
            raise RuntimeError("Coverbase session did not include user_input_followups")

        updated_followups = copy.deepcopy(existing_followups)
        updated_user_followups = copy.deepcopy(existing_user_followups)
        answered_ids = {
            question_id
            for question_id, response in hazel_responses.items()
            if self._hazel_response_value(response) is not None
        }
        matched_ids: set[str] = set()
        for followup in updated_followups:
            if not isinstance(followup, dict):
                continue
            local_question_id = self._question_id(followup)
            if local_question_id not in answered_ids:
                continue
            value = self._hazel_response_value(hazel_responses[local_question_id])
            if value is None:
                continue
            response = hazel_responses[local_question_id]
            custom = (
                str(response.get("custom") or "").strip()
                if isinstance(response, dict)
                else ""
            )
            choice = (
                str(response.get("choice") or "").strip()
                if isinstance(response, dict)
                else ""
            )
            if choice and not custom:
                options = followup.get("options") or []
                if value not in options:
                    raise RuntimeError(
                        "Hazel selected an option that Coverbase did not return for "
                        f"{local_question_id}"
                    )
            followup["response"] = value
            matched_ids.add(local_question_id)

        unmatched_ids = sorted(answered_ids - matched_ids)
        if unmatched_ids:
            raise RuntimeError(
                "Hazel responses no longer match the current Coverbase Step 2 questions: "
                + ", ".join(unmatched_ids)
            )
        if not matched_ids:
            raise RuntimeError("No answered Hazel responses matched Coverbase Step 2 questions")

        contact_index = self._primary_contact_followup_index(updated_user_followups)
        if contact_index is None:
            raise RuntimeError(
                "Coverbase Step 2 did not include the Hazel primary-contact follow-up"
            )
        primary_contact = self._primary_contact_data(submit_interest)
        updated_user_followups[contact_index]["response"] = " | ".join(
            (
                primary_contact["name"],
                primary_contact["title"],
                primary_contact["email"],
                primary_contact["phone_number"],
            )
        )
        updated_user_followups[contact_index]["response_data"] = {
            "type": "contacts",
            "contacts": [primary_contact],
        }
        logger.info(
            "[Coverbase] mapped Hazel Submit Interest primary contact to Coverbase follow-up"
        )

        mapped_count = len(matched_ids)
        logger.info(
            "[Coverbase] mapped %s Hazel responses to %s ai_generated_followups",
            mapped_count,
            mapped_count,
        )
        update_path = f"{INTAKE_SESSION_PATH}/{session_id}"
        process_path = f"{update_path}/actions/process_all_questions"
        update_payload = {
            "session_data": {
                "ai_generated_followups": updated_followups,
                "user_input_followups": updated_user_followups,
            }
        }

        if self.mode == "mock":
            logger.info("[Coverbase] POST %s", update_path)
            logger.info("[Coverbase] Step 2 responses saved")
            logger.info("[Coverbase] POST /actions/process_all_questions")
            logger.info("[Coverbase] questionnaire processing started")
            logger.info("[Coverbase] questionnaire processing complete")
            return {
                "mapped_responses": mapped_count,
                "updated_followups": mapped_count,
                "questionnaire_processing": False,
                "questionnaire_responses_populated": True,
                "questionnaire_response_count": len(MOCK_QUESTIONS),
                "process_all_questions_status": 200,
            }

        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=60.0, headers=self._headers()
        ) as client:
            logger.info("[Coverbase] POST %s", update_path)
            update_response = await client.post(update_path, json=update_payload)
            update_response.raise_for_status()
            logger.info("[Coverbase] Step 2 responses saved")

            logger.info("[Coverbase] POST /actions/process_all_questions")
            process_response = await client.post(process_path)
            process_response.raise_for_status()
            logger.info("[Coverbase] questionnaire processing started")

        questionnaire_response_count = 0
        processing_complete = False
        provider_is_processing: bool | None = None
        for attempt in range(QUESTIONNAIRE_PROCESSING_POLL_ATTEMPTS):
            if attempt:
                await asyncio.sleep(QUESTIONNAIRE_PROCESSING_POLL_SECONDS)
            current_session = await self._get_portal_intake_session(session_id)
            current_data = current_session.get("session_data")
            if not isinstance(current_data, dict):
                raise RuntimeError("Coverbase polling response did not include session_data")
            provider_is_processing = current_data.get("is_processing_questions") is True
            questionnaire_responses = current_data.get("questionnaire_responses")
            questionnaire_response_count = (
                len(questionnaire_responses)
                if isinstance(questionnaire_responses, list)
                else 0
            )
            if not provider_is_processing and questionnaire_response_count > 0:
                processing_complete = True
                logger.info("[Coverbase] questionnaire processing complete")
                break

        if not processing_complete:
            logger.info("[Coverbase] questionnaire processing continues asynchronously")
        return {
            "mapped_responses": mapped_count,
            "updated_followups": mapped_count,
            "questionnaire_processing": not processing_complete,
            "coverbase_is_processing_questions": provider_is_processing,
            "questionnaire_responses_populated": questionnaire_response_count > 0,
            "questionnaire_response_count": questionnaire_response_count,
            "process_all_questions_status": process_response.status_code,
        }

    @staticmethod
    def _hazel_response_value(response: Any) -> str | None:
        if isinstance(response, str):
            value = response.strip()
            return value or None
        if not isinstance(response, dict):
            return None
        custom = str(response.get("custom") or "").strip()
        choice = str(response.get("choice") or "").strip()
        return custom or choice or None

    @staticmethod
    def _primary_contact_followup_index(
        user_followups: list[Any],
    ) -> int | None:
        for index, followup in enumerate(user_followups):
            if (
                isinstance(followup, dict)
                and followup.get("question_id") == PRIMARY_CONTACT_QUESTION_ID
            ):
                return index
        for index, followup in enumerate(user_followups):
            if not isinstance(followup, dict):
                continue
            question = " ".join(
                str(followup.get("question") or "").casefold().split()
            )
            if (
                followup.get("response_type") == "contacts"
                and "primary contact" in question
                and ("hazel" in question or "relationship" in question)
            ):
                return index
        return None

    @staticmethod
    def _primary_contact_data(submit_interest: dict[str, Any]) -> dict[str, str]:
        contact_fields = (
            ("contact_name", "contact name"),
            ("contact_title", "contact title"),
            ("contact_email", "contact email"),
            ("phone", "contact phone"),
        )
        values = [str(submit_interest.get(key) or "").strip() for key, _ in contact_fields]
        missing = [
            label
            for value, (_, label) in zip(values, contact_fields)
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Hazel Submit Interest primary contact is incomplete: "
                + ", ".join(missing)
            )
        return {
            "name": values[0],
            "title": values[1],
            "linkedin": str(
                submit_interest.get("contact_linkedin")
                or submit_interest.get("linkedin")
                or ""
            ).strip(),
            "email": values[2],
            "phone_number": values[3],
        }

    @staticmethod
    def select_hazel_use_case(options: list[str]) -> str:
        """Choose an exact Coverbase option using Hazel's banking preference order."""
        normalized_options = [
            (option, " ".join(option.casefold().split())) for option in options
        ]
        for concept in HAZEL_USE_CASE_CONCEPTS:
            for option, normalized_option in normalized_options:
                if concept in normalized_option:
                    return option
        raise RuntimeError(
            "Coverbase Step 1 returned no banking or financial-services-related "
            f"use case. Available options: {options}"
        )

    @classmethod
    def institution_profile_schema(cls, ai_followups: list[dict[str, Any]]) -> dict[str, Any]:
        """Transform ai_generated_followups into Hazel's existing React schema."""
        questions: list[dict[str, Any]] = []
        responses: dict[str, dict[str, str]] = {}
        for record in ai_followups:
            if not isinstance(record, dict) or not record.get("question"):
                continue
            question = cls._schema_question(record)
            questions.append(question)
            cls._collect_response(record, question, responses)

        if not questions:
            raise RuntimeError("Coverbase response did not include Institution Profile questions")
        return {
            "schema_version": "coverbase-intake-session-v1",
            "title": "Institution Profile",
            "description": "Provide additional details about your institution and intended use of the Hazel Network.",
            "sections": [
                {
                    "id": "coverbase-additional-information",
                    "title": "Additional Information",
                    "kind": "questions",
                    "questions": questions,
                    "supporting_information": {
                        "label": "Custom response",
                        "placeholder": "Or write a custom answer",
                    },
                }
            ],
            "responses": responses,
        }

    @staticmethod
    def _question_id(record: dict[str, Any]) -> str:
        provider_id = record.get("question_id") or record.get("id")
        if provider_id:
            return str(provider_id)
        identity = json.dumps(
            {"question": record.get("question"), "options": record.get("options") or []},
            sort_keys=True,
            ensure_ascii=True,
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return f"coverbase_ai_{digest}"

    @classmethod
    def _schema_question(cls, record: dict[str, Any]) -> dict[str, Any]:
        raw_options = record.get("options") or []
        if not isinstance(raw_options, list):
            raw_options = []
        options = []
        for option in raw_options:
            if isinstance(option, str):
                options.append(option)
            elif isinstance(option, dict):
                label = option.get("label") or option.get("name") or option.get("value")
                if label:
                    options.append(str(label))
        return {
            "id": cls._question_id(record),
            "label": str(record["question"]),
            "options": options,
            "response_type": record.get("response_type"),
        }

    @staticmethod
    def _collect_response(
        record: dict[str, Any],
        question: dict[str, Any],
        responses: dict[str, dict[str, str]],
    ) -> None:
        value = record.get("response")
        if value in (None, "", []):
            return
        if isinstance(value, list):
            value = value[0] if len(value) == 1 else ", ".join(str(item) for item in value)
        text = str(value)
        options = question.get("options") or []
        responses[question["id"]] = {
            "choice": text if text in options else "",
            "custom": "" if text in options else text,
        }

    async def get_risk_questions(self, session_id: str) -> dict[str, Any]:
        """Load the generated Coverbase questionnaire without local substitutes."""
        logger.info("[Coverbase] loading Risk Questions for session %s", session_id)
        intake_session = await self._get_portal_intake_session(session_id)
        session_data = intake_session.get("session_data")
        if not isinstance(session_data, dict):
            raise RuntimeError("Coverbase response did not include session_data")

        is_processing = session_data.get("is_processing_questions") is True
        raw_responses = session_data.get("questionnaire_responses")
        responses = raw_responses if isinstance(raw_responses, list) else []
        if is_processing or not responses:
            return {
                "status": "processing",
                "questions": [],
                "debug": self._risk_debug_metrics(session_id, responses, is_processing),
            }

        questionnaire_ids = list(
            dict.fromkeys(
                str(item.get("questionnaire_id"))
                for item in responses
                if isinstance(item, dict) and item.get("questionnaire_id")
            )
        )
        metadata_by_id: dict[str, dict[str, Any]] = {}
        for questionnaire_id in questionnaire_ids:
            try:
                metadata_by_id[questionnaire_id] = await self._get_questionnaire_metadata(
                    session_id, questionnaire_id
                )
            except (httpx.HTTPError, RuntimeError) as exc:
                # The provider responses remain usable even if optional presentation
                # metadata is temporarily unavailable.
                logger.warning(
                    "[Coverbase] questionnaire metadata unavailable for %s: %s",
                    questionnaire_id,
                    exc,
                )

        questions = [
            self._normalize_risk_question(item, metadata_by_id)
            for item in responses
            if isinstance(item, dict)
        ]
        logger.info("[Coverbase] loaded %s questionnaire_responses", len(questions))
        return {
            "status": "ready",
            "questions": questions,
            "debug": self._risk_debug_metrics(session_id, responses, is_processing),
        }

    async def submit_risk_questions(self, session_id: str) -> dict[str, Any]:
        """Validate the current provider state and submit it for internal review."""
        if self._pending_questionnaire_saves.get(session_id, 0) > 0:
            raise CoverbaseQuestionnaireSavePending(
                "Wait for the current Risk Question save to finish before submitting."
            )

        # Always refetch immediately before submission. This is the authoritative
        # state after Hazel's individual response writes.
        intake_session = await self._get_portal_intake_session(session_id)
        current_status = str(intake_session.get("status") or "")
        if current_status in {
            "submitted",
            "pending_review",
            "accepted",
            "rejected",
            "partial",
        }:
            return intake_session

        session_data = intake_session.get("session_data")
        if not isinstance(session_data, dict):
            raise RuntimeError("Coverbase response did not include session_data")
        if session_data.get("is_processing_questions") is True:
            raise CoverbaseQuestionnaireSavePending(
                "Coverbase is still preparing questionnaire responses. Try again shortly."
            )
        raw_responses = session_data.get("questionnaire_responses")
        if not isinstance(raw_responses, list) or not raw_responses:
            raise RuntimeError("Coverbase session did not include questionnaire_responses")
        responses = [item for item in raw_responses if isinstance(item, dict)]

        questionnaire_ids = list(
            dict.fromkeys(
                str(item.get("questionnaire_id"))
                for item in responses
                if item.get("questionnaire_id")
            )
        )
        if not questionnaire_ids:
            raise RuntimeError(
                "Coverbase questionnaire responses did not include questionnaire IDs"
            )
        metadata_by_id = {
            questionnaire_id: await self._get_questionnaire_metadata(
                session_id, questionnaire_id
            )
            for questionnaire_id in questionnaire_ids
        }
        normalized = [
            self._normalize_risk_question(item, metadata_by_id) for item in responses
        ]
        missing_question_ids = [
            str(question.get("question_id"))
            for question in normalized
            if question.get("is_required") is True
            and not self._risk_response_is_valid(question)
        ]
        if missing_question_ids:
            raise CoverbaseSubmissionValidationError(
                "Complete all required Risk Questions before submitting. Missing: "
                + ", ".join(missing_question_ids),
                missing_question_ids,
            )

        path = f"{INTAKE_SESSION_PATH}/{session_id}"
        payload = {"status": "submitted"}
        logger.info("[Coverbase] submitting Risk Questions for session %s", session_id)
        logger.info("[Coverbase] POST %s with status submitted", path)
        if self.mode == "mock":
            self._mock_session_statuses[session_id] = "submitted"
            submitted = await self._get_portal_intake_session(session_id)
            logger.info("[Coverbase] Risk Questions submission response status 200")
            return submitted

        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=60.0, headers=self._headers()
        ) as client:
            response = await client.post(path, json=payload)
            logger.info(
                "[Coverbase] Risk Questions submission response status %s",
                response.status_code,
            )
            if not response.is_success:
                try:
                    error_payload = response.json()
                except (TypeError, ValueError):
                    error_payload = {}
                detail = (
                    error_payload.get("detail")
                    if isinstance(error_payload, dict)
                    else None
                )
                if (
                    isinstance(detail, dict)
                    and detail.get("error_code") == "missing_required_questions"
                ):
                    missing = detail.get("missing_question_ids")
                    missing_ids = (
                        [str(value) for value in missing]
                        if isinstance(missing, list)
                        else []
                    )
                    message = str(
                        detail.get("message")
                        or "Coverbase reports that required Risk Questions are missing."
                    )
                    raise CoverbaseSubmissionValidationError(message, missing_ids)
                response.raise_for_status()
            submitted = response.json()
        if not isinstance(submitted, dict):
            raise RuntimeError("Coverbase submission response was not an object")
        return submitted

    async def get_review_status(self, session_id: str) -> dict[str, Any]:
        """Return only member-safe workflow fields from the current intake session."""
        logger.info("[Coverbase] loading Hazel Review status for session %s", session_id)
        intake_session = await self._get_portal_intake_session(session_id)
        return {
            "session_id": str(intake_session.get("id") or session_id),
            "status": str(intake_session.get("status") or "unknown"),
            "vendor_id": intake_session.get("vendor_id"),
        }

    async def update_risk_question_response(
        self,
        session_id: str,
        question_id: str,
        updates: dict[str, Any],
        supplied_fields: set[str],
    ) -> dict[str, Any]:
        self._pending_questionnaire_saves[session_id] = (
            self._pending_questionnaire_saves.get(session_id, 0) + 1
        )
        try:
            return await self._update_risk_question_response(
                session_id, question_id, updates, supplied_fields
            )
        finally:
            remaining = self._pending_questionnaire_saves.get(session_id, 1) - 1
            if remaining > 0:
                self._pending_questionnaire_saves[session_id] = remaining
            else:
                self._pending_questionnaire_saves.pop(session_id, None)

    async def _update_risk_question_response(
        self,
        session_id: str,
        question_id: str,
        updates: dict[str, Any],
        supplied_fields: set[str],
    ) -> dict[str, Any]:
        """Write one full questionnaire response back to its Coverbase session."""
        intake_session = await self._get_portal_intake_session(session_id)
        session_data = intake_session.get("session_data")
        if not isinstance(session_data, dict):
            raise RuntimeError("Coverbase response did not include session_data")
        if session_data.get("is_processing_questions") is True:
            raise RuntimeError("Coverbase questionnaire responses are still processing")
        responses = session_data.get("questionnaire_responses")
        if not isinstance(responses, list):
            raise RuntimeError("Coverbase session did not include questionnaire_responses")

        current = next(
            (
                item
                for item in responses
                if isinstance(item, dict) and str(item.get("question_id")) == question_id
            ),
            None,
        )
        if current is None:
            raise ValueError("Coverbase questionnaire response was not found")
        if not current.get("questionnaire_id") or not current.get("question_id"):
            raise RuntimeError("Coverbase questionnaire response is missing provider IDs")

        questionnaire_id = str(current["questionnaire_id"])
        metadata = await self._get_questionnaire_metadata(session_id, questionnaire_id)
        metadata_by_id = {questionnaire_id: metadata}
        normalized = self._normalize_risk_question(current, metadata_by_id)
        response_type = str(current.get("response_type") or "")

        updated = copy.deepcopy(current)
        new_response = updates["response"]
        selected_option_ids = updates.get("selected_option_ids")
        if response_type in {"select_one", "single_select", "select_multiple", "multi_select"}:
            if selected_option_ids is None:
                if new_response != current.get("response"):
                    raise ValueError(
                        "selected_option_ids is required when changing a select response"
                    )
                selected_option_ids = copy.deepcopy(current.get("selected_option_ids"))
            selected_option_ids = selected_option_ids or []
            option_by_id = {
                str(option["id"]): option["label"]
                for option in normalized.get("options", [])
                if option.get("id")
            }
            if not option_by_id:
                raise RuntimeError(
                    "Coverbase option metadata is unavailable; response was not changed"
                )
            unknown_ids = [
                option_id
                for option_id in selected_option_ids
                if str(option_id) not in option_by_id
            ]
            if unknown_ids:
                raise ValueError(
                    "selected_option_ids contains IDs not returned by Coverbase: "
                    + ", ".join(str(value) for value in unknown_ids)
                )
            if response_type in {"select_one", "single_select"} and len(selected_option_ids) > 1:
                raise ValueError("A select-one response may contain at most one option ID")
            expected_response = ", ".join(
                option_by_id[str(option_id)] for option_id in selected_option_ids
            )
            selection_changed = (
                new_response != current.get("response")
                or selected_option_ids != (current.get("selected_option_ids") or [])
            )
            if selection_changed and new_response != expected_response:
                raise ValueError(
                    "response must exactly match the Coverbase option selected by ID"
                )
            updated["selected_option_ids"] = [str(value) for value in selected_option_ids]
        elif "selected_option_ids" in supplied_fields:
            updated["selected_option_ids"] = selected_option_ids

        if response_type == "contacts":
            contact_data = self._normalize_contacts_response_data(
                updates.get("response_data")
            )
            updated["response_data"] = contact_data
            updated["response"] = "; ".join(
                " — ".join(
                    value
                    for value in (
                        contact["name"],
                        contact["email"],
                        contact["phone_number"],
                        contact["title"],
                        contact["linkedin"],
                    )
                    if value
                )
                for contact in contact_data["contacts"]
            )
        else:
            updated["response"] = new_response
            if "response_data" in supplied_fields:
                updated["response_data"] = updates.get("response_data")
        if "comment" in supplied_fields:
            updated["comment"] = updates.get("comment")
        updated["reviewed"] = True

        response_changed = any(
            updated.get(field) != current.get(field)
            for field in ("response", "selected_option_ids", "response_data")
        )
        if response_changed:
            if updated.get("original_ai_response") is None:
                updated["original_ai_response"] = current.get("response")
            if updated.get("original_ai_selected_option_ids") is None:
                updated["original_ai_selected_option_ids"] = copy.deepcopy(
                    current.get("selected_option_ids")
                )
            updated["is_ai_generated"] = False

        path = f"{INTAKE_SESSION_PATH}/{session_id}/questionnaire_response"
        logger.info(
            "[Coverbase] POST %s for question %s", path, current["question_id"]
        )
        if self.mode == "mock":
            stored_responses = copy.deepcopy(responses)
            for index, response_item in enumerate(stored_responses):
                if (
                    isinstance(response_item, dict)
                    and str(response_item.get("question_id")) == question_id
                ):
                    stored_responses[index] = copy.deepcopy(updated)
                    break
            self._mock_questionnaire_response_overrides[session_id] = stored_responses
            response_status = 200
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=60.0, headers=self._headers()
            ) as client:
                response = await client.post(path, json={"response": updated})
                response_status = response.status_code
                logger.info(
                    "[Coverbase] questionnaire response status %s", response_status
                )
                response.raise_for_status()
        logger.info(
            "[Coverbase] saved reviewed response for question %s", current["question_id"]
        )
        return {
            "status": "saved",
            "question": self._normalize_risk_question(updated, metadata_by_id),
            "coverbase_response_status": response_status,
        }

    async def _get_questionnaire_metadata(
        self, session_id: str, questionnaire_id: str
    ) -> dict[str, Any]:
        if self.mode == "mock":
            return self._mock_questionnaire_metadata(questionnaire_id)
        path = (
            f"{INTAKE_SESSION_PATH}/{session_id}/questionnaire/{questionnaire_id}"
        )
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=60.0, headers=self._headers()
        ) as client:
            response = await client.get(path)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Coverbase questionnaire metadata was not an object")
        nested = payload.get("questionnaire") or payload.get("data")
        return nested if isinstance(nested, dict) else payload

    @staticmethod
    def _normalize_risk_question(
        response: dict[str, Any],
        metadata_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if not response.get("question_id") or not response.get("questionnaire_id"):
            raise RuntimeError("Coverbase questionnaire response is missing provider IDs")
        normalized = copy.deepcopy(response)
        questionnaire = metadata_by_id.get(str(response["questionnaire_id"]), {})
        questions = questionnaire.get("questions") or []
        question_meta = next(
            (
                question
                for question in questions
                if isinstance(question, dict)
                and str(question.get("id")) == str(response["question_id"])
            ),
            {},
        )
        sections = questionnaire.get("sections") or []
        section_id = question_meta.get("section_id")
        section_meta = next(
            (
                section
                for section in sections
                if isinstance(section, dict)
                and str(section.get("id")) == str(section_id)
            ),
            {},
        )
        options: list[dict[str, Any]] = []
        for option in question_meta.get("options") or []:
            if not isinstance(option, dict) or not option.get("id"):
                continue
            options.append(
                {
                    "id": str(option["id"]),
                    "label": str(option.get("name") or option.get("label") or ""),
                    **{
                        key: copy.deepcopy(value)
                        for key, value in option.items()
                        if key not in {"id", "name", "label"}
                    },
                }
            )
        normalized.update(
            {
                "section_id": section_id,
                "section_name": section_meta.get("name") or "Questionnaire",
                "section_sort_order": section_meta.get("sort_order"),
                "question_sort_order": question_meta.get("sort_order"),
                "options": options,
                "is_required": (
                    question_meta.get("is_required")
                    if question_meta.get("is_required") is not None
                    else response.get("is_required")
                ),
                "user_review_required": question_meta.get("user_review_required"),
                "additional_instructions": question_meta.get("additional_instructions"),
                "reasoning": response.get("detailed_reasoning"),
                "confidence": response.get("ai_confidence"),
            }
        )
        review_state = CoverbaseService._risk_review_state(response)
        if response.get("response_type") == "contacts" and review_state == "needs_input":
            # Coverbase can retain reviewed=true on an empty contact widget. Hazel
            # must classify the actual contact payload, not that stale flag.
            normalized["reviewed"] = False
        normalized["review_state"] = review_state
        return normalized

    @staticmethod
    def _contacts_response_is_populated(response_data: Any) -> bool:
        if not isinstance(response_data, dict):
            return False
        if response_data.get("type") != "contacts":
            return False
        contacts = response_data.get("contacts")
        if not isinstance(contacts, list):
            return False
        identifying_fields = ("name", "email", "phone_number", "linkedin")
        return any(
            isinstance(contact, dict)
            and any(
                str(contact.get(field) or "").strip()
                for field in identifying_fields
            )
            for contact in contacts
        )

    @staticmethod
    def _normalize_contacts_response_data(response_data: Any) -> dict[str, Any]:
        if not isinstance(response_data, dict) or response_data.get("type") != "contacts":
            raise ValueError("A contacts response requires Coverbase contacts response_data")
        raw_contacts = response_data.get("contacts")
        if not isinstance(raw_contacts, list) or not 1 <= len(raw_contacts) <= 6:
            raise ValueError("A contacts response requires between 1 and 6 contacts")

        contacts = []
        for index, raw_contact in enumerate(raw_contacts, start=1):
            if not isinstance(raw_contact, dict):
                raise ValueError(f"Contact {index} was not a valid contact object")
            contact = {
                "name": str(raw_contact.get("name") or "").strip(),
                "title": str(raw_contact.get("title") or "").strip(),
                "linkedin": str(raw_contact.get("linkedin") or "").strip(),
                "email": str(raw_contact.get("email") or "").strip(),
                "phone_number": str(raw_contact.get("phone_number") or "").strip(),
            }
            if not contact["name"]:
                raise ValueError(f"Contact {index} requires a name")
            if not contact["email"] and not contact["phone_number"]:
                raise ValueError(
                    f"Contact {index} requires an email address or phone number"
                )
            contacts.append(contact)
        return {"type": "contacts", "contacts": contacts}

    @classmethod
    def _risk_response_is_empty(cls, response: dict[str, Any]) -> bool:
        if response.get("response_type") == "contacts":
            return not cls._contacts_response_is_populated(
                response.get("response_data")
            )
        return (
            response.get("response") in (None, "", [])
            and response.get("selected_option_ids") in (None, [], "")
            and response.get("response_data") in (None, {}, [], "")
        )

    @classmethod
    def _risk_response_is_valid(cls, response: dict[str, Any]) -> bool:
        response_type = str(response.get("response_type") or "")
        if response_type == "contacts":
            return cls._contacts_response_is_populated(response.get("response_data"))
        if response_type in {"select_one", "single_select"}:
            selected = response.get("selected_option_ids")
            return (
                isinstance(selected, list)
                and len(selected) == 1
                and bool(str(response.get("response") or "").strip())
            )
        if response_type in {"select_multiple", "multi_select"}:
            selected = response.get("selected_option_ids")
            return isinstance(selected, list) and len(selected) > 0
        return not cls._risk_response_is_empty(response)

    @classmethod
    def _risk_review_state(cls, response: dict[str, Any]) -> str:
        is_empty = cls._risk_response_is_empty(response)
        if response.get("response_type") == "contacts" and is_empty:
            return "needs_input"
        if response.get("reviewed") is True:
            return "reviewed"
        return "needs_input" if is_empty else "needs_review"

    @classmethod
    def _risk_debug_metrics(
        cls,
        session_id: str,
        responses: list[Any],
        is_processing: bool,
    ) -> dict[str, Any]:
        valid = [item for item in responses if isinstance(item, dict)]
        review_states = [cls._risk_review_state(item) for item in valid]
        reviewed_count = review_states.count("reviewed")
        needs_input_count = review_states.count("needs_input")
        needs_review_count = review_states.count("needs_review")
        return {
            "coverbase_session_id": session_id,
            "questionnaire_response_count": len(valid),
            "is_processing_questions": is_processing,
            "reviewed_count": reviewed_count,
            "ai_generated_count": sum(
                item.get("is_ai_generated") is True for item in valid
            ),
            "needs_input_count": needs_input_count,
            "needs_review_count": needs_review_count,
            "requires_member_action_count": needs_input_count + needs_review_count,
        }

    # Backward-compatible names for the existing Hazel router.
    async def create_intake(
        self, case_id: str, profile: dict[str, Any], due_diligence: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.create_intake_session(case_id, profile, due_diligence)

    async def get_intake(self, session_id: str) -> dict[str, Any]:
        return await self.get_intake_session(session_id)

    @staticmethod
    def build_context(profile: dict[str, Any], due_diligence: dict[str, Any]) -> str:
        excluded = {"case_id", "updated_at", "data_json"}
        profile_lines = [
            f"{key}: {value}" for key, value in profile.items() if value and key not in excluded
        ]
        diligence_lines = [f"{key}: {value}" for key, value in due_diligence.items() if value]
        return (
            "Hazel Express Interest\n"
            + "\n".join(profile_lines)
            + "\n\nDue Diligence\n"
            + "\n".join(diligence_lines)
        )


coverbase_service = CoverbaseService()
