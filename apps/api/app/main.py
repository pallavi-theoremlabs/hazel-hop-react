import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from app.config import settings, validate_backend_settings
from app.db import connection, credential_status, init_db
from app.lakebase import assert_sdk_capabilities, sdk_version
from app.routers.cases import canonical_router, router as cases_router
from app.routers.dev import router as dev_router
from app.routers.public import router as public_router
from app.storage import probe_storage, storage
from app.tenancy import SYSTEM_SESSION, require_proxy, require_tenant

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # First, and before anything opens a connection: which SDK the container
    # actually resolved is the first question asked whenever an API surface moves,
    # and the assertion below is only legible next to the answer.
    assert_sdk_capabilities()
    logger.info("[Hazel] databricks-sdk=%s", sdk_version())
    validate_backend_settings()
    probe_storage()
    init_db()
    yield


app = FastAPI(title="Hazel HOP API", version="0.1.0", lifespan=lifespan)

# No CORS middleware, deliberately.
#
# The React UI is served from Azure and never calls this API from the browser. It
# cannot: a Databricks App is behind the workspace auth proxy, and a CORS preflight
# is sent without credentials, so it is rejected before the real request is ever
# attempted. An Azure backend-for-frontend forwards /api/* instead, which is a
# server-to-server call with no Origin header and no preflight.
#
# So CORSMiddleware would not be in the request path even if it were configured,
# and configuring it anyway would suggest browser-direct access is a supported
# topology when it is not. See app/tenancy.py.

# The public router and a three-route integration onboarding slice are mounted.
#
# postgres setup/hazel_schema.sql is the final schema, and it has no
# institution_profiles, express_interest_submissions, due_diligence or
# review_clarifications. The remaining routes in cases_router and dev_router query
# at least one of them, so mounting either would publish endpoints that answer 500
# with an UndefinedTable — failures that read like bugs in this service rather than
# like work that has not been done yet. They are re-mounted as each is ported.
#
# What survives is the public inquiry flow:
#
#     GET /api/banks/{cert}   ->  RAFA over HTTP  ->  JSON
#     POST /api/submit-interest -> institution, user, case and RAFA rows
#
# canonical_router contains only case load, NDA acceptance and Coverbase session
# creation. The shared BFF supplies the real institution context and require_tenant
# establishes the Lakebase RLS session. The remaining case and developer routes
# stay parked until they are ported to the same schema.
app.include_router(public_router, dependencies=[Depends(require_proxy)])
app.include_router(canonical_router, dependencies=[Depends(require_tenant)])

_PARKED = (cases_router, dev_router)  # noqa: F841 — named so the imports stay honest


@app.get("/api/health")
def health():
    """Liveness plus the two things that actually break in production.

    Database reachability and credential age are what the token-rotation soak
    watches: drive traffic past the TTL and `credential.fingerprint` must change.
    A 503 here means the app is up but cannot serve requests, which is a different
    and more useful signal than the process simply being alive.
    """
    database = {"reachable": True}
    try:
        # SYSTEM: /api/health is intentionally outside the tenancy dependencies, so
        # there is no request session to inherit, and it only ever runs SELECT 1.
        with connection(session=SYSTEM_SESSION) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:  # surfaced deliberately; this is the diagnostic path
        database = {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}
        logger.warning("[Hazel] health check: database unreachable: %s", exc)

    payload = {
        "status": "ok" if database["reachable"] else "degraded",
        "coverbase_mode": settings.coverbase_mode,
        "database": database,
        "credential": credential_status(),
        "storage": {"backend": storage.backend, "location": storage.location},
        # Readable without log access, which is the case that matters when the app
        # is up but a dependency has moved underneath it.
        "sdk": {"databricks_sdk": sdk_version()},
    }
    return JSONResponse(payload, status_code=200 if database["reachable"] else 503)


# ---------------------------------------------------------------------------
# No static frontend
# ---------------------------------------------------------------------------
#
# This process used to serve frontend/dist as well, behind a catch-all that
# returned index.html for client-side routes. The UI is hosted on Azure now, so
# that block is gone rather than left in place as a fallback.
#
# It was not harmless to keep. The catch-all matched "/{full_path:path}", so the
# App would answer every unrouted path with whatever copy of the UI happened to be
# committed at deploy time — a second, silently stale frontend on a URL nobody
# intends to visit, diverging from Azure the moment either side ships. Without it,
# an unmatched path gets FastAPI's own 404, which is the correct answer from an API.
#
# Retiring this also retires the reason frontend/dist had to be committed at all
# (see .gitignore) — Databricks Apps does not run `npm run build`, but nothing here
# needs the build any more.
