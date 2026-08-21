import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.routers import cases


CASE_ID = "11111111-1111-4111-8111-111111111111"
INSTITUTION_ID = "22222222-2222-4222-8222-222222222222"


class Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class CanonicalDatabase:
    def __init__(self):
        self.case = {
            "id": CASE_ID,
            "institution_id": INSTITUTION_ID,
            "case_number": "HZL-INT-TEST",
            "current_stage": "NDA",
            "current_status": "AWAITING_MEMBER",
            "decision_status": "PENDING",
            "coverbase_session_id": None,
            "coverbase_vendor_id": None,
            "coverbase_questionnaire_id": None,
            "coverbase_session_status": "NOT_CREATED",
            "coverbase_assessment_status": "NOT_STARTED",
            "coverbase_sync_status": "NOT_APPLICABLE",
            "coverbase_last_synced_at": None,
        }
        self.institution = {
            "legal_name": "Canonical Community Bank",
            "institution_type": "NATIONAL_BANK",
            "registration_contact_email": "applicant@example.com",
            "primary_applicant_email": "applicant@example.com",
            "website": "https://canonical.example",
        }
        self.transition_at = None
        self.statements = []

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        self.statements.append((normalized, tuple(params)))
        if normalized.startswith("SELECT * FROM onboarding_case"):
            return Result(dict(self.case))
        if normalized.startswith(("SELECT legal_name", "SELECT i.legal_name")):
            return Result(dict(self.institution))
        if normalized.startswith("SELECT occurred_at FROM case_stage_transition"):
            return Result(
                {"occurred_at": self.transition_at} if self.transition_at else None
            )
        if normalized.startswith("SELECT set_config"):
            return Result({})
        if "SET current_stage = 'RISK_ASSESSMENT'" in normalized:
            self.case["current_stage"] = "RISK_ASSESSMENT"
            self.case["current_status"] = "IN_PROGRESS"
            self.transition_at = datetime(2026, 8, 21, 16, 0, tzinfo=timezone.utc)
            return Result()
        if "coverbase_session_status = 'IN_PROGRESS'" in normalized:
            self.case["coverbase_session_status"] = "IN_PROGRESS"
            self.case["coverbase_sync_status"] = "IN_PROGRESS"
            return Result()
        if "coverbase_session_status = 'NOT_CREATED'" in normalized:
            self.case["coverbase_session_status"] = "NOT_CREATED"
            self.case["coverbase_sync_status"] = "FAILED"
            return Result()
        if "RETURNING *" in normalized and "coverbase_session_id" in normalized:
            self.case.update(
                coverbase_session_id=params[0],
                coverbase_vendor_id=params[1],
                coverbase_questionnaire_id=params[2],
                coverbase_session_status="CREATED",
                coverbase_assessment_status="NOT_STARTED",
                coverbase_sync_status="SYNCED",
                coverbase_last_synced_at=params[3],
            )
            return Result(dict(self.case))
        raise AssertionError(f"Unexpected SQL: {normalized}")


class CanonicalOnboardingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.database = CanonicalDatabase()

        @contextmanager
        def fake_connection(*_args, **_kwargs):
            yield self.database

        self.connection_patch = patch.object(cases, "connection", fake_connection)
        self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)

    def assert_no_legacy_sql(self):
        legacy = {
            "onboarding_cases",
            "express_interest_submissions",
            "institution_profiles",
            "due_diligence",
            "documents",
            "review_clarifications",
            "case_decisions",
        }
        sql = "\n".join(statement for statement, _ in self.database.statements)
        for table in legacy:
            self.assertNotIn(table, sql)

    async def test_case_load_projects_canonical_case_for_current_portal(self):
        payload = cases.get_case(CASE_ID)

        self.assertEqual(payload["canonical_current_stage"], "NDA")
        self.assertEqual(payload["current_stage"], "NDA_PENDING")
        self.assertEqual(payload["legal_name"], "Canonical Community Bank")
        self.assertEqual(payload["primary_applicant_email"], "applicant@example.com")
        self.assertIsNone(payload["nda_accepted_at"])
        self.assert_no_legacy_sql()

    async def test_only_three_canonical_routes_are_exposed(self):
        routes = {
            (route.path, tuple(sorted(route.methods)))
            for route in cases.canonical_router.routes
        }
        self.assertEqual(
            routes,
            {
                ("/api/cases/{case_id}", ("GET",)),
                ("/api/cases/{case_id}/nda/accept", ("POST",)),
                ("/api/cases/{case_id}/coverbase/session", ("POST",)),
            },
        )

    async def test_nda_accept_creates_and_persists_one_coverbase_session(self):
        create_session = AsyncMock(
            return_value={
                "session_id": "cb-session-1",
                "vendor_id": "cb-vendor-1",
                "status": "open",
            }
        )
        with (
            patch.object(cases.coverbase_service, "create_intake_session", create_session),
            patch.object(
                cases,
                "settings",
                SimpleNamespace(coverbase_questionnaire_id="cb-questionnaire-1"),
            ),
        ):
            result = await cases.accept_nda(CASE_ID)
            reused = await cases.create_coverbase_session(CASE_ID)

        self.assertEqual(self.database.case["current_stage"], "RISK_ASSESSMENT")
        self.assertEqual(self.database.case["coverbase_session_id"], "cb-session-1")
        self.assertEqual(self.database.case["coverbase_session_status"], "CREATED")
        self.assertEqual(self.database.case["coverbase_sync_status"], "SYNCED")
        self.assertEqual(result["current_stage"], "RISK_ASSESSMENT")
        self.assertEqual(result["coverbase_session_id"], "cb-session-1")
        self.assertTrue(reused["reused"])
        create_session.assert_awaited_once()
        request_profile = create_session.await_args.args[1]
        self.assertEqual(request_profile["legal_name"], "Canonical Community Bank")
        self.assertEqual(request_profile["website"], "https://canonical.example")
        self.assert_no_legacy_sql()

if __name__ == "__main__":
    unittest.main()
