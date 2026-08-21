import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABRICKS_HOST", "https://workspace.example")
os.environ.setdefault("DATABRICKS_CLIENT_ID", "client-id")
os.environ.setdefault("DATABRICKS_CLIENT_SECRET", "client-secret")
os.environ.setdefault("DATABRICKS_APP_URL", "https://app.example")
os.environ.setdefault("HAZEL_PROXY_KEY", "proxy-key")

from fastapi import HTTPException
from starlette.requests import Request

import proxy


CASE_ID = "11111111-1111-4111-8111-111111111111"
INSTITUTION_ID = "22222222-2222-4222-8222-222222222222"


def request(headers=None):
    raw_headers = [
        (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
    ]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw_headers})


class DevelopmentSessionTests(unittest.TestCase):
    def test_bridge_requires_mode_and_exact_onboarding_path(self):
        incoming = request({proxy.DEV_INSTITUTION_HEADER: INSTITUTION_ID})
        path = f"/api/cases/{CASE_ID}"

        with patch.object(proxy, "HAZEL_DEV_MODE", False):
            self.assertIsNone(proxy.resolve_session(incoming, path))
        with patch.object(proxy, "HAZEL_DEV_MODE", True):
            self.assertEqual(
                proxy.resolve_session(incoming, path),
                (INSTITUTION_ID, None, "MEMBER_ADMIN"),
            )
            self.assertIsNone(proxy.resolve_session(incoming, f"{path}/documents"))

    def test_bridge_rejects_invalid_institution_uuid(self):
        incoming = request({proxy.DEV_INSTITUTION_HEADER: "not-a-uuid"})
        with patch.object(proxy, "HAZEL_DEV_MODE", True):
            with self.assertRaises(HTTPException) as raised:
                proxy.resolve_session(incoming, f"/api/cases/{CASE_ID}/nda/accept")
        self.assertEqual(raised.exception.status_code, 400)

    def test_browser_dev_header_is_always_stripped_before_forwarding(self):
        self.assertIn("x-hazel-dev-institution-id", proxy.STRIPPED_REQUEST_HEADERS)


if __name__ == "__main__":
    unittest.main()
