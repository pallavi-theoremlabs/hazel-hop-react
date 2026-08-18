import unittest
from unittest.mock import AsyncMock, patch

from app.db import connection, init_db
from app.tenancy import SYSTEM_SESSION
from app.routers import public
from app.schemas import SubmitInterestCreate


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


@unittest.skip(
    "Pending the four-table decision. submit_interest writes to organizations, "
    "institutions, rafa_screenings, onboarding_cases, express_interest_submissions, "
    "institution_profiles and due_diligence — none of which exist in the final "
    "schema (postgres setup/hazel_schema.sql). Skipped rather than deleted: the "
    "assertions describe the intended behaviour and are the specification to port "
    "the endpoint against."
)
class SubmitInterestRafaTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    async def test_eligible_profile_creates_nda_case_without_coverbase(self):
        profile = bank_profile("30001", "900001", 3.0, "accepted")
        with patch.object(public.rafa_service, "lookup_bank", AsyncMock(return_value=profile)):
            result = await public.submit_interest(submission("30001"))
        self.assertTrue(result["eligible"])
        self.assertEqual(result["current_stage"], "NDA_PENDING")
        self.assertIsNone(result["coverbase_session_id"])
        with connection(session=SYSTEM_SESSION) as conn:
            case = conn.execute(
                "SELECT * FROM onboarding_cases WHERE id = %s", (result["case_id"],)
            ).fetchone()
            inquiry = conn.execute(
                "SELECT * FROM express_interest_submissions WHERE case_id = %s",
                (result["case_id"],),
            ).fetchone()
            screening = conn.execute(
                "SELECT * FROM rafa_screenings WHERE institution_id = %s",
                (result["institution_id"],),
            ).fetchone()
        self.assertEqual(case["current_stage"], "NDA_PENDING")
        self.assertIsNone(case["coverbase_session_id"])
        self.assertEqual(inquiry["legal_name"], profile["legal_name"])
        self.assertEqual(inquiry["rssd_id"], profile["rssd_id"])
        self.assertEqual(screening["rafa_status"], "accepted")

    async def test_rejected_profile_has_no_secure_onboarding_path(self):
        profile = bank_profile("20001", "900002", 2.99, "rejected")
        with patch.object(public.rafa_service, "lookup_bank", AsyncMock(return_value=profile)):
            result = await public.submit_interest(submission("20001"))
        self.assertFalse(result["eligible"])
        self.assertIsNone(result["next_path"])
        with connection(session=SYSTEM_SESSION) as conn:
            case = conn.execute(
                "SELECT * FROM onboarding_cases WHERE id = %s", (result["case_id"],)
            ).fetchone()
            profile_row = conn.execute(
                "SELECT * FROM institution_profiles WHERE case_id = %s",
                (result["case_id"],),
            ).fetchone()
        self.assertEqual(case["current_stage"], "INQUIRY_REJECTED")
        self.assertIsNone(case["coverbase_session_id"])
        self.assertIsNone(profile_row)


if __name__ == "__main__":
    unittest.main()
