"""Backend-only adapter for Hazel's RAFA / Bank Profile lookup."""

from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("uvicorn.error")


class RafaError(RuntimeError):
    """Base class for member-safe RAFA integration failures."""


class RafaNotFound(RafaError):
    """No institution exists for the supplied FDIC certificate."""


class RafaAuthenticationError(RafaError):
    """The backend RAFA credential was rejected."""


class RafaProviderUnavailable(RafaError):
    """RAFA failed or returned an unusable response."""


class RafaService:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        provider: str | None = None,
    ):
        self.provider = provider or settings.rafa_provider
        self.base_url = settings.rafa_base_url
        self.api_key = settings.rafa_api_key
        self.minimum_score = Decimal(str(settings.rafa_eligibility_min_score))
        self._transport = transport
        self.databricks_host = settings.databricks_host
        self.databricks_client_id = settings.databricks_client_id
        self.databricks_client_secret = settings.databricks_client_secret
        self.databricks_app_url = settings.databricks_app_url
        self._databricks_access_token: str | None = None
        self._databricks_token_expires_at = 0.0

    async def lookup_bank(self, fdic_certificate_number: str) -> dict[str, Any]:
        certificate = str(fdic_certificate_number).strip()
        if not certificate.isdigit():
            raise ValueError("FDIC certificate number must contain digits only")

        logger.info(
            "[RAFA] looking up FDIC certificate %s via %s",
            certificate,
            self.provider,
        )
        if self.provider == "databricks":
            payload = await self._lookup_databricks_app_bank(certificate)
            return self.normalize_bank(payload, requested_certificate=certificate)
        if self.provider != "onrender":
            raise RafaProviderUnavailable("RAFA provider is not supported")

        return await self._lookup_onrender_bank(certificate)

    async def _lookup_onrender_bank(self, certificate: str) -> dict[str, Any]:
        if not self.base_url or not self.api_key:
            raise RafaProviderUnavailable("RAFA is not configured")

        path = f"/banks/{certificate}"
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers={"x-api-key": self.api_key},
                timeout=20.0,
                transport=self._transport,
            ) as client:
                response = await client.get(path)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning("[RAFA] provider unavailable for FDIC %s", certificate)
            raise RafaProviderUnavailable("RAFA is temporarily unavailable") from exc

        logger.info("[RAFA] lookup response status %s", response.status_code)
        if response.status_code == 404:
            raise RafaNotFound("No institution matched that FDIC certificate number")
        if response.status_code in {401, 403}:
            logger.error("[RAFA] backend authentication failed")
            raise RafaAuthenticationError("RAFA authentication failed")
        if response.status_code >= 500:
            raise RafaProviderUnavailable("RAFA is temporarily unavailable")
        if not response.is_success:
            raise RafaProviderUnavailable("RAFA could not complete the lookup")

        try:
            payload = response.json()
        except ValueError as exc:
            raise RafaProviderUnavailable("RAFA returned invalid JSON") from exc
        return self.normalize_bank(payload, requested_certificate=certificate)

    async def _get_databricks_access_token(self) -> str:
        if self._databricks_access_token and time.monotonic() < (
            self._databricks_token_expires_at - 60
        ):
            return self._databricks_access_token
        if not all(
            (
                self.databricks_host,
                self.databricks_client_id,
                self.databricks_client_secret,
            )
        ):
            raise RafaProviderUnavailable("Databricks RAFA is not configured")

        try:
            async with httpx.AsyncClient(
                timeout=20.0, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self.databricks_host}/oidc/v1/token",
                    auth=(
                        self.databricks_client_id,
                        self.databricks_client_secret,
                    ),
                    data={"grant_type": "client_credentials", "scope": "all-apis"},
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning("[RAFA] Databricks OAuth unavailable")
            raise RafaProviderUnavailable("RAFA is temporarily unavailable") from exc

        if response.status_code in {401, 403}:
            logger.error("[RAFA] Databricks OAuth authentication failed")
            raise RafaAuthenticationError("RAFA authentication failed")
        if not response.is_success:
            logger.warning(
                "[RAFA] Databricks OAuth response status %s", response.status_code
            )
            raise RafaProviderUnavailable("RAFA is temporarily unavailable")

        try:
            token_payload = response.json()
            access_token = str(token_payload.get("access_token") or "")
            expires_in = int(token_payload.get("expires_in") or 3600)
        except (TypeError, ValueError) as exc:
            raise RafaProviderUnavailable("RAFA returned an invalid OAuth response") from exc
        if not access_token:
            raise RafaProviderUnavailable("RAFA returned an invalid OAuth response")

        self._databricks_access_token = access_token
        self._databricks_token_expires_at = time.monotonic() + max(expires_in, 0)
        return access_token

    async def _lookup_databricks_app_bank(self, certificate: str) -> dict[str, Any]:
        if not self.databricks_app_url:
            raise RafaProviderUnavailable("Databricks RAFA is not configured")
        token = await self._get_databricks_access_token()
        try:
            async with httpx.AsyncClient(
                timeout=20.0, transport=self._transport
            ) as client:
                response = await client.get(
                    f"{self.databricks_app_url}/banks/{certificate}",
                    headers={"Authorization": f"Bearer {token}"},
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.warning("[RAFA] Databricks App unavailable")
            raise RafaProviderUnavailable("RAFA is temporarily unavailable") from exc

        logger.info("[RAFA] Databricks App response status %s", response.status_code)
        if response.status_code == 404:
            raise RafaNotFound("No institution matched that FDIC certificate number")
        if response.status_code in {401, 403}:
            logger.error("[RAFA] Databricks App authorization failed")
            raise RafaAuthenticationError("RAFA authentication failed")
        if not response.is_success:
            raise RafaProviderUnavailable("RAFA is temporarily unavailable")

        try:
            payload = response.json()
        except ValueError as exc:
            raise RafaProviderUnavailable("RAFA returned invalid JSON") from exc

        logger.info("[RAFA] Databricks App lookup succeeded")
        return payload

    def normalize_bank(
        self, payload: object, *, requested_certificate: str
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RafaProviderUnavailable("RAFA bank profile was not an object")

        certificate = str(payload.get("fdic_cert_number") or "").strip()
        legal_name = str(payload.get("bank_name") or "").strip()
        rssd_id = str(payload.get("rssd_id") or "").strip()
        raw_score = str(payload.get("composite_score") or "").strip()
        if not certificate or certificate != requested_certificate or not legal_name:
            raise RafaProviderUnavailable("RAFA bank profile was missing identity fields")
        try:
            score = Decimal(raw_score)
        except (InvalidOperation, ValueError) as exc:
            raise RafaProviderUnavailable("RAFA bank profile had an invalid score") from exc

        # Temporary testing policy explicitly approved for this MVP.
        status = "accepted" if score >= self.minimum_score else "rejected"
        street_2 = str(payload.get("STREET_LINE2") or "").strip()
        address_parts = [
            str(payload.get("STREET_LINE1") or "").strip(),
            "" if street_2 == "0" else street_2,
            str(payload.get("CITY") or "").strip(),
            str(payload.get("STATE_ABBR_NM") or "").strip(),
            str(payload.get("ZIP_CD") or "").strip(),
            str(payload.get("CNTRY_NM") or "").strip(),
        ]
        return {
            "fdic_certificate_number": certificate,
            "rssd_id": rssd_id or None,
            "legal_name": legal_name,
            "rafa_score": float(score),
            "rafa_status": status,
            "rating_label": str(payload.get("rating_label") or "").strip() or None,
            "composite_rating": str(payload.get("composite_rating") or "").strip() or None,
            "profile_year": str(payload.get("year") or "").strip() or None,
            "profile_quarter": str(payload.get("quarter") or "").strip() or None,
            "headquarters": ", ".join(part for part in address_parts if part),
        }


rafa_service = RafaService()
