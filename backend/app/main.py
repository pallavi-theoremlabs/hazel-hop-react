import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings, validate_backend_settings
from app.db import init_db
from app.routers.cases import router as cases_router
from app.routers.dev import router as dev_router
from app.routers.public import router as public_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_backend_settings()
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
    return {"status": "ok", "coverbase_mode": settings.coverbase_mode}
