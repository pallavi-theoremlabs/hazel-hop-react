import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABRICKS_HOST", "https://workspace.example")
os.environ.setdefault("DATABRICKS_CLIENT_ID", "client-id")
os.environ.setdefault("DATABRICKS_CLIENT_SECRET", "client-secret")
os.environ.setdefault("DATABRICKS_APP_URL", "https://app.example")
os.environ.setdefault("HAZEL_PROXY_KEY", "proxy-key")
os.environ["FRONTEND_ORIGINS"] = (
    "https://frontend-hop.onrender.com,"
    "https://member-portal-c4k9.onrender.com"
)

from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import proxy


CASE_ID = "11111111-1111-4111-8111-111111111111"
INSTITUTION_ID = "22222222-2222-4222-8222-222222222222"
PUBLIC_ORIGIN = "https://frontend-hop.onrender.com"
MEMBER_ORIGIN = "https://member-portal-c4k9.onrender.com"


def request(headers=None, method="GET"):
    raw_headers = [
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    ]
    return Request({"type": "http", "method": method, "path": "/", "headers": raw_headers})


class IntegrationSessionTests(unittest.TestCase):
    def test_bridge_accepts_only_exact_onboarding_method_and_path(self):
        incoming = request({proxy.INTEGRATION_INSTITUTION_HEADER: INSTITUTION_ID})
        post = request(
            {proxy.INTEGRATION_INSTITUTION_HEADER: INSTITUTION_ID}, method="POST"
        )
        path = f"/api/cases/{CASE_ID}"

        self.assertEqual(
            proxy.resolve_session(incoming, path),
            (INSTITUTION_ID, None, "MEMBER_ADMIN"),
        )
        self.assertEqual(
            proxy.resolve_session(post, f"{path}/coverbase/session"),
            (INSTITUTION_ID, None, "MEMBER_ADMIN"),
        )
        self.assertEqual(
            proxy.resolve_session(post, f"{path}/nda/accept"),
            (INSTITUTION_ID, None, "MEMBER_ADMIN"),
        )
        self.assertIsNone(proxy.resolve_session(incoming, f"{path}/nda/accept"))
        self.assertIsNone(proxy.resolve_session(post, path))
        self.assertIsNone(proxy.resolve_session(incoming, f"{path}/documents"))

    def test_bridge_rejects_invalid_institution_uuid(self):
        incoming = request(
            {proxy.INTEGRATION_INSTITUTION_HEADER: "not-a-uuid"}, method="POST"
        )
        with self.assertRaises(HTTPException) as raised:
            proxy.resolve_session(incoming, f"/api/cases/{CASE_ID}/nda/accept")
        self.assertEqual(raised.exception.status_code, 400)

    def test_browser_integration_header_is_always_stripped_before_forwarding(self):
        self.assertIn(
            "x-hazel-integration-institution-id", proxy.STRIPPED_REQUEST_HEADERS
        )


class CorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(proxy.app)

    def preflight(self, origin):
        return self.client.options(
            "/api/submit-interest",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )

    def test_public_origin_is_allowed(self):
        response = self.preflight(PUBLIC_ORIGIN)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], PUBLIC_ORIGIN)

    def test_member_origin_is_allowed(self):
        response = self.preflight(MEMBER_ORIGIN)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], MEMBER_ORIGIN)

    def test_member_integration_context_header_is_allowed(self):
        response = self.client.options(
            f"/api/cases/{CASE_ID}",
            headers={
                "Origin": MEMBER_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": proxy.INTEGRATION_INSTITUTION_HEADER,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            proxy.INTEGRATION_INSTITUTION_HEADER.lower(),
            response.headers["access-control-allow-headers"].lower(),
        )

    def test_unknown_origin_is_rejected(self):
        response = self.preflight("https://untrusted.example")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_health_route_is_unaffected(self):
        response = self.client.get("/healthz", headers={"Origin": PUBLIC_ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response.headers["access-control-allow-origin"], PUBLIC_ORIGIN)

    def test_singular_origin_setting_remains_a_fallback(self):
        with patch.dict(
            os.environ,
            {"FRONTEND_ORIGIN": f" {PUBLIC_ORIGIN}, {MEMBER_ORIGIN} "},
            clear=True,
        ):
            self.assertEqual(
                proxy.configured_frontend_origins(),
                [PUBLIC_ORIGIN, MEMBER_ORIGIN],
            )

    def test_wildcard_origin_is_rejected(self):
        with patch.dict(os.environ, {"FRONTEND_ORIGINS": "*"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "explicit allowlist"):
                proxy.configured_frontend_origins()


if __name__ == "__main__":
    unittest.main()
