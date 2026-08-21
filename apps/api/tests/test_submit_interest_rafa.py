import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch
from uuid import UUID

from app.routers import public
from app.schemas import SubmitInterestCreate


SUBMISSION_ID = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")


def bank_profile(certificate, rssd_id, score, status):
    return {
        "fdic_certificate_number": certificate,
        "rssd_id": rssd_id,
        "legal_name": f"RAFA TEST BANK {certificate}",
        "rafa_score": score,
        "rafa_status": status,
        "rating_label": "Test rating",
        "composite_rating": "3",
        "profile_year": "2025",
        "profile_quarter": "3",
        "headquarters": "Test City, TX, UNITED STATES",
    }


def submission(certificate):
    return SubmitInterestCreate(
        legal_name="Member-entered name",
        fdic_certificate_number=certificate,
        website="https://example.com",
        institution_type="National bank",
        contact_name="Test Applicant",
        contact_title="Officer",
        contact_email="applicant@example.com",
        phone="555-0100",
        reason_for_interest="Testing",
    )


class FakeCursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class RecordingConnection:
    def __init__(self, active_case=None):
        self.active_case = active_case
        self.statements = []

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        self.statements.append((normalized, tuple(params)))
        if normalized.startswith("SELECT id, case_number FROM onboarding_case"):
            return FakeCursor(self.active_case)
        return FakeCursor()

    def statement(self, prefix):
        return next(item for item in self.statements if item[0].startswith(prefix))


class SubmitInterestRafaTests(unittest.IsolatedAsyncioTestCase):
    async def run_submission(self, profile, active_case=None):
        database = RecordingConnection(active_case=active_case)
        sessions = []

        @contextmanager
        def fake_connection(session=None):
            sessions.append(session)
            yield database

        with (
            patch.object(
                public.rafa_service,
                "lookup_bank",
                AsyncMock(return_value=profile),
            ),
            patch.object(public, "connection", fake_connection),
            patch.object(public, "uuid4", return_value=SUBMISSION_ID),
        ):
            result = await public.submit_interest(
                submission(profile["fdic_certificate_number"])
            )
        return result, database, sessions

    async def test_eligible_profile_creates_live_schema_rows(self):
        profile = bank_profile("30001", "900001", 3.0, "accepted")
        result, database, sessions = await self.run_submission(profile)

        institution_id = public.institution_id_for_certificate("30001")
        self.assertEqual(sessions, [(institution_id, None, "SYSTEM")])
        self.assertTrue(result["eligible"])
        self.assertEqual(result["case_id"], str(SUBMISSION_ID))
        self.assertEqual(result["institution_id"], institution_id)
        self.assertEqual(result["current_stage"], "NDA_PENDING")
        self.assertEqual(result["next_path"], f"/case/{SUBMISSION_ID}/nda")

        institution = database.statement("INSERT INTO institution")
        self.assertEqual(institution[1][3:5], ("NATIONAL_BANK", "ONBOARDING"))

        user = database.statement('INSERT INTO "user"')
        self.assertEqual(user[1][3:6], ("applicant@example.com", "Test", "Applicant"))

        case = database.statement("INSERT INTO onboarding_case")
        self.assertEqual(case[1][3:6], ("NDA", "AWAITING_MEMBER", "PENDING"))
        self.assertIsNone(case[1][7])

        rafa = database.statement("INSERT INTO rafa")
        self.assertEqual(rafa[1][4], "PASS")

        sql = " ".join(statement for statement, _ in database.statements)
        for retired_table in (
            "organizations",
            "institutions",
            "rafa_screenings",
            "onboarding_cases",
            "express_interest_submissions",
            "institution_profiles",
            "due_diligence",
        ):
            self.assertNotIn(retired_table, sql)

    async def test_rejected_profile_creates_terminal_case(self):
        profile = bank_profile("20001", "900002", 2.99, "rejected")
        result, database, _ = await self.run_submission(profile)

        self.assertFalse(result["eligible"])
        self.assertEqual(result["current_stage"], "INQUIRY_REJECTED")
        self.assertIsNone(result["next_path"])

        institution = database.statement("INSERT INTO institution")
        self.assertEqual(institution[1][4], "DECLINED")

        case = database.statement("INSERT INTO onboarding_case")
        self.assertEqual(
            case[1][3:6],
            ("ELIGIBILITY_SCREENING", "DECLINED", "DECLINED"),
        )
        self.assertIsNotNone(case[1][7])

        rafa = database.statement("INSERT INTO rafa")
        self.assertEqual(rafa[1][4], "DECLINE")

    async def test_repeat_eligible_submission_reuses_active_case(self):
        existing = {
            "id": UUID("11111111-2222-4333-8444-555555555555"),
            "case_number": "HZL-INT-EXISTING",
        }
        profile = bank_profile("30001", "900001", 3.0, "accepted")
        result, database, _ = await self.run_submission(profile, active_case=existing)

        self.assertEqual(result["case_id"], str(existing["id"]))
        self.assertEqual(result["inquiry_reference"], existing["case_number"])
        with self.assertRaises(StopIteration):
            database.statement("INSERT INTO onboarding_case")
        database.statement("INSERT INTO rafa")


if __name__ == "__main__":
    unittest.main()
