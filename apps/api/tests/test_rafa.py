import unittest
from urllib.parse import parse_qs

import httpx

from app.services.rafa import (
    RafaAuthenticationError,
    RafaNotFound,
    RafaProviderUnavailable,
    RafaService,
)


PROFILE = {
    "CITY": "COLUMBUS",
    "CNTRY_NM": "UNITED STATES",
    "STATE_ABBR_NM": "OH",
    "STREET_LINE1": "1111 POLARIS PARKWAY",
    "STREET_LINE2": "0",
    "ZIP_CD": "43240",
    "bank_name": "TEST BANK, NATIONAL ASSOCIATION",
    "composite_rating": "3",
    "composite_score": "3.00",
    "fdic_cert_number": "628",
    "quarter": "3",
    "rating_label": "Test rating",
    "rssd_id": "852218",
    "year": "2025",
}


class RafaServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_normalizes_verified_fields_and_applies_temporary_threshold(self):
        async def handler(request):
            self.assertEqual(request.headers.get("x-api-key"), "test-secret")
            return httpx.Response(200, json=PROFILE)

        service = RafaService(
            transport=httpx.MockTransport(handler), provider="onrender"
        )
        service.base_url = "https://rafa.test"
        service.api_key = "test-secret"
        service.minimum_score = 3
        result = await service.lookup_bank("628")
        self.assertEqual(result["legal_name"], PROFILE["bank_name"])
        self.assertEqual(result["rssd_id"], PROFILE["rssd_id"])
        self.assertEqual(result["rafa_score"], 3.0)
        self.assertEqual(result["rafa_status"], "accepted")

        below = {**PROFILE, "composite_score": "2.99"}
        result = service.normalize_bank(below, requested_certificate="628")
        self.assertEqual(result["rafa_status"], "rejected")

    async def test_not_found_is_distinct_from_rejection(self):
        service = self.service_for_status(404)
        with self.assertRaises(RafaNotFound):
            await service.lookup_bank("999999")

    async def test_authentication_failure_is_not_rejection(self):
        service = self.service_for_status(401)
        with self.assertRaises(RafaAuthenticationError):
            await service.lookup_bank("628")

    async def test_provider_failure_is_not_rejection(self):
        service = self.service_for_status(503)
        with self.assertRaises(RafaProviderUnavailable):
            await service.lookup_bank("628")

    @staticmethod
    def service_for_status(status):
        service = RafaService(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, json={"detail": "test"})
            ),
            provider="onrender",
        )
        service.base_url = "https://rafa.test"
        service.api_key = "test-secret"
        return service

    async def test_databricks_lookup_uses_oauth_and_app_url(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.url.path == "/oidc/v1/token":
                self.assertEqual(request.method, "POST")
                self.assertTrue(request.headers["authorization"].startswith("Basic "))
                self.assertEqual(
                    parse_qs(request.content.decode()),
                    {"grant_type": ["client_credentials"], "scope": ["all-apis"]},
                )
                return httpx.Response(
                    200,
                    json={
                        "access_token": "test-token",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    },
                )
            self.assertEqual(request.url.path, "/banks/628")
            self.assertEqual(request.headers["authorization"], "Bearer test-token")
            return httpx.Response(200, json=PROFILE)

        service = RafaService(
            provider="databricks",
            transport=httpx.MockTransport(handler),
        )
        service.databricks_host = "https://workspace.test"
        service.databricks_client_id = "client-id"
        service.databricks_client_secret = "client-secret"
        service.databricks_app_url = "https://app.test"
        service.minimum_score = 3

        result = await service.lookup_bank("628")

        self.assertEqual(result["legal_name"], PROFILE["bank_name"])
        self.assertEqual(result["rafa_status"], "accepted")
        self.assertEqual(len(requests), 2)

    async def test_databricks_app_not_found_is_distinct_from_rejection(self):
        def handler(request):
            if request.url.path == "/oidc/v1/token":
                return httpx.Response(
                    200, json={"access_token": "test-token", "expires_in": 3600}
                )
            return httpx.Response(404, json={"detail": "not found"})

        service = RafaService(
            provider="databricks",
            transport=httpx.MockTransport(handler),
        )
        service.databricks_host = "https://workspace.test"
        service.databricks_client_id = "client-id"
        service.databricks_client_secret = "client-secret"
        service.databricks_app_url = "https://app.test"
        with self.assertRaises(RafaNotFound):
            await service.lookup_bank("999999")


if __name__ == "__main__":
    unittest.main()
