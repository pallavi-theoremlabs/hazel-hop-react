import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import BACKEND_DIR, settings, validate_backend_settings
from app.db import connection, credential_status, init_db
from app.routers.cases import router as cases_router
from app.routers.dev import router as dev_router
from app.routers.public import router as public_router
from app.storage import probe_storage, storage

logger = logging.getLogger("uvicorn.error")

FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"
INDEX_HTML = FRONTEND_DIST / "index.html"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_backend_settings()
    probe_storage()
    init_db()
    yield


app = FastAPI(title="Hazel HOP API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(cases_router)
app.include_router(dev_router)
app.include_router(public_router)


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
        with connection() as conn:
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
    }
    return JSONResponse(payload, status_code=200 if database["reachable"] else 503)


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------
#
# Registered after the API routers so it cannot take precedence over them.
#
# StaticFiles(html=True) is deliberately NOT used as the whole answer: it serves
# index.html for *directory* requests only, so a deep link such as
# /case/HAZEL-TEST-001/documents has no matching file on disk and 404s. Client-side
# routing needs an explicit catch-all instead.
#
# The catch-all must also refuse /api/* itself. Route ordering alone is not enough:
# an unmatched /api/nonexistent falls past every router and would otherwise be
# answered with index.html — an API client would receive 200 and a page of HTML
# instead of a 404.

if INDEX_HTML.is_file():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(404, "Not found")

        if full_path:
            candidate = (FRONTEND_DIST / full_path).resolve()
            # Containment check: full_path is attacker-controlled and may contain
            # traversal segments, so a resolved path outside dist/ is refused
            # rather than served.
            if candidate.is_file() and candidate.is_relative_to(FRONTEND_DIST.resolve()):
                return FileResponse(candidate)

        return FileResponse(INDEX_HTML)

    logger.info("[Hazel] serving frontend from %s", FRONTEND_DIST)
else:
    logger.warning(
        "[Hazel] no frontend build at %s; API-only. Run `npm run build` in frontend/ "
        "and commit frontend/dist/ before deploying.",
        FRONTEND_DIST,
    )
