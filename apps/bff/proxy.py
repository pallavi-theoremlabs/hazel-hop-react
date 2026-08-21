"""Render backend-for-frontend: the only thing that talks to the Databricks App.

Why this tier exists at all
---------------------------
A Databricks App sits behind the workspace authentication proxy, and there is no
anonymous mode. A browser cannot satisfy it for three independent reasons, any one
of which would be enough:

  * The end users are banks applying for membership. They have no Databricks
    identity, so SSO has nothing to authenticate them as.
  * A SPA bundle is public, so it cannot hold the service principal secret that
    would mint a token. Shipping one would publish workspace credentials.
  * A CORS preflight is sent without credentials, by specification. The auth proxy
    rejects the OPTIONS, so the real request is never attempted — this breaks
    browser-direct access even when a token is available.

So the token is minted here, server-side, where the secret can live.

The browser talks only to this tier, never to the App. Whether that is same-origin
depends on how it is deployed: served from one host alongside the SPA it is, and
no CORS is involved; deployed as its own service — which is what Render does — it
is not, and FRONTEND_ORIGINS below has to name each SPA origin so the preflight
is answered. The App itself still needs no CORS either way, because this hop is
server-to-server and carries no Origin header.

This mirrors the token handling already in apps/api/app/services/rafa.py, which
calls a *different* Databricks App the same way.

Runs on any host that can hold a secret and reach the workspace — currently Render.
Prefer a plan without cold starts: uploads are multipart up to 25MB and are
streamed through below rather than buffered.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

logger = logging.getLogger("uvicorn.error")


def _required(name: str) -> str:
    value = os.getenv(name, "").strip().rstrip("/")
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


DATABRICKS_HOST = _required("DATABRICKS_HOST")
DATABRICKS_CLIENT_ID = _required("DATABRICKS_CLIENT_ID")
DATABRICKS_CLIENT_SECRET = _required("DATABRICKS_CLIENT_SECRET")
DATABRICKS_APP_URL = _required("DATABRICKS_APP_URL")

# Must match HAZEL_PROXY_KEY in the App's app.yaml. The API refuses every request
# without it, so a mismatch here presents as a uniform 401 rather than as partial
# breakage.
HAZEL_PROXY_KEY = _required("HAZEL_PROXY_KEY")
INTEGRATION_INSTITUTION_HEADER = "X-Hazel-Integration-Institution-Id"
INTEGRATION_CASE_PATH = (
    r"/api/cases/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
INTEGRATION_ONBOARDING_ROUTES = {
    "GET": re.compile(rf"^{INTEGRATION_CASE_PATH}$"),
    "POST": re.compile(rf"^{INTEGRATION_CASE_PATH}(?:/nda/accept|/coverbase/session)$"),
}

# /api/dev/* is not forwarded. Those endpoints create and destroy synthetic cases,
# and reset-case deletes a case's documents. The integration app needs only the
# three exact real-case routes above.
BLOCKED_PREFIXES = ("/api/dev",)

# Hop-by-hop headers, plus the ones that must be recomputed for the upstream
# request rather than copied. Host would otherwise carry this tier's hostname to
# Databricks, and Authorization is ours to set. Content-Length is dropped because
# the body is re-streamed and httpx recomputes framing.
STRIPPED_REQUEST_HEADERS = {
    "host",
    "authorization",
    "content-length",
    "connection",
    "keep-alive",
    "transfer-encoding",
    "upgrade",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    # Never forwarded from the client: these are what the App trusts to identify
    # the caller and the tenant, and this tier is the only thing entitled to set
    # them. Without this, a browser could name any institution it liked and RLS
    # would faithfully serve that tenant's data.
    #
    # These four are the session contract from postgres setup/hazel_schema.sql —
    # institution, user and role — plus the key proving the hop came from here.
    "x-hazel-proxy-key",
    "x-hazel-institution-id",
    "x-hazel-user-id",
    "x-hazel-role",
    "x-hazel-integration-institution-id",
}

STRIPPED_RESPONSE_HEADERS = {
    "content-length",
    "content-encoding",
    "connection",
    "keep-alive",
    "transfer-encoding",
}

app = FastAPI(title="Hazel HOP proxy")

# CORS, and the reason it is needed here rather than on the Databricks App.
#
# The original design put the SPA and this proxy on one origin, which is why the
# App itself registers no CORS middleware and does not need to: a server-to-server
# forward sends no Origin header and triggers no preflight. Deployed as two
# separate Render services, that assumption no longer holds — the browser calls
# a different host and sends a preflight, so this tier has to answer it.
#
# Explicit origins, never "*": allow_origins=["*"] is rejected by browsers in
# combination with credentials, and an open policy on a tier holding workspace
# credentials is worth avoiding regardless.
#
# The App is still not reachable from a browser directly — it sits behind the
# Databricks auth proxy, which rejects the unauthenticated preflight. This makes
# the *proxy* callable from the SPA, which is the only hop that should be.
def configured_frontend_origins() -> list[str]:
    """Return the explicit browser-origin allowlist.

    FRONTEND_ORIGINS is the canonical setting. FRONTEND_ORIGIN remains a
    fallback so existing deployments can move to the plural name without a
    flag day. Both accept comma-separated values; duplicates are removed while
    preserving the configured order.
    """
    raw_origins = os.getenv("FRONTEND_ORIGINS") or os.getenv("FRONTEND_ORIGIN", "")
    origins = (origin.strip() for origin in raw_origins.split(","))
    allowlist = list(dict.fromkeys(origin for origin in origins if origin))
    if "*" in allowlist:
        raise RuntimeError("FRONTEND_ORIGINS must be an explicit allowlist, not '*'")
    return allowlist


FRONTEND_ORIGINS = configured_frontend_origins()
if FRONTEND_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=FRONTEND_ORIGINS,
        # No cookies are involved: the browser authenticates to this tier not at
        # all, and this tier authenticates to Databricks with its own credential.
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    logger.info("[proxy] CORS enabled for %s", FRONTEND_ORIGINS)
else:
    # Not fatal: a same-origin deployment genuinely needs no CORS, and refusing to
    # start would break that topology. Logged because the symptom otherwise shows
    # up only in a browser console, as a failure that looks like the API is down.
    logger.warning(
        "[proxy] FRONTEND_ORIGINS and FRONTEND_ORIGIN are unset; "
        "no CORS headers will be sent. "
        "Browser calls from a different origin will fail their preflight."
    )

_token: str | None = None
_token_expires_at = 0.0
_token_lock = asyncio.Lock()


async def access_token(client: httpx.AsyncClient) -> str:
    """A workspace OAuth token, cached until shortly before it expires.

    The lock makes a cold start mint once rather than once per concurrent request.
    The 60-second margin covers a token that would otherwise expire in flight.
    """
    global _token, _token_expires_at

    if _token and time.monotonic() < _token_expires_at - 60:
        return _token

    async with _token_lock:
        if _token and time.monotonic() < _token_expires_at - 60:
            return _token

        response = await client.post(
            f"{DATABRICKS_HOST}/oidc/v1/token",
            auth=(DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET),
            data={"grant_type": "client_credentials", "scope": "all-apis"},
        )
        if response.status_code in {401, 403}:
            logger.error("[proxy] Databricks OAuth rejected the service principal")
            raise HTTPException(502, "Upstream authentication failed")
        if not response.is_success:
            logger.error("[proxy] Databricks OAuth returned %s", response.status_code)
            raise HTTPException(502, "Upstream authentication failed")

        payload = response.json()
        token = str(payload.get("access_token") or "")
        if not token:
            raise HTTPException(502, "Upstream authentication returned no token")

        _token = token
        _token_expires_at = time.monotonic() + int(payload.get("expires_in") or 3600)
        return token


def resolve_session(
    request: Request, target_path: str
) -> tuple[str, str | None, str] | None:
    """Resolve the tenant context for the throwaway integration application."""
    authenticated = getattr(request.state, "session", None)
    if authenticated:
        return authenticated

    # This throwaway integration app deliberately has no user authentication. It
    # accepts a browser-carried tenant id only for the three exact method/path
    # combinations above, then translates it into the trusted headers consumed by
    # the Databricks API and Lakebase RLS.
    route_pattern = INTEGRATION_ONBOARDING_ROUTES.get(request.method.upper())
    if route_pattern and route_pattern.fullmatch(target_path):
        raw = request.headers.get(INTEGRATION_INSTITUTION_HEADER, "").strip()
        if raw:
            try:
                institution_id = str(UUID(raw))
            except ValueError as exc:
                raise HTTPException(
                    400, f"{INTEGRATION_INSTITUTION_HEADER} is not a valid UUID"
                ) from exc
            return institution_id, None, "MEMBER_ADMIN"
    return None


@app.api_route(
    "/api/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def forward(path: str, request: Request):
    target_path = f"/api/{path}"
    if any(target_path.startswith(prefix) for prefix in BLOCKED_PREFIXES):
        raise HTTPException(404, "Not found")

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in STRIPPED_REQUEST_HEADERS
    }
    headers["X-Hazel-Proxy-Key"] = HAZEL_PROXY_KEY

    session = resolve_session(request, target_path)
    if session:
        institution_id, user_id, role = session
        headers["X-Hazel-Institution-Id"] = institution_id
        headers["X-Hazel-Role"] = role
        if user_id:
            headers["X-Hazel-User-Id"] = user_id

    # A single client for both calls so the token request and the forwarded request
    # share a connection pool. stream=True keeps 25MB uploads and document
    # downloads off this tier's heap.
    client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    try:
        headers["Authorization"] = f"Bearer {await access_token(client)}"

        upstream = client.build_request(
            request.method,
            f"{DATABRICKS_APP_URL}{target_path}",
            headers=headers,
            params=request.query_params,
            content=request.stream(),
        )
        response = await client.send(upstream, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning("[proxy] upstream request failed: %s", exc)
        raise HTTPException(502, "Upstream request failed") from exc
    except Exception:
        await client.aclose()
        raise

    async def body():
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        body(),
        status_code=response.status_code,
        headers={
            key: value
            for key, value in response.headers.items()
            if key.lower() not in STRIPPED_RESPONSE_HEADERS
        },
        media_type=response.headers.get("content-type"),
    )


@app.get("/healthz")
async def healthz():
    """This tier's own liveness. Deliberately does not call upstream.

    Render restarts an instance that fails its health check, and a Databricks-side
    outage is not something restarting this process would fix. Use /api/health
    through the proxy to check the App.
    """
    return {"status": "ok"}
