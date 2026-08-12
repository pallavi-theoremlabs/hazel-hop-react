"""Backend-only configuration loaded from the backend project's .env file."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger("uvicorn.error")

BACKEND_DIR = Path(__file__).resolve().parents[1]
BACKEND_ENV_PATH = BACKEND_DIR / ".env"

# A missing .env is normal in a deployed environment, where configuration arrives
# as real environment variables and no file is shipped. This used to raise at
# *import* time, which killed the process before FastAPI could start and produced
# a container that exited with a traceback and no served endpoint. Load the file
# when it is there, and otherwise fall through to the process environment.
#
# The path is anchored to this module, so loading never depends on the working
# directory, and override=False means injected variables always beat the file.
if BACKEND_ENV_PATH.is_file():
    DOTENV_LOADED = load_dotenv(dotenv_path=BACKEND_ENV_PATH, override=False)
else:
    DOTENV_LOADED = False
    logger.info(
        "No %s; reading configuration from the process environment.", BACKEND_ENV_PATH
    )


@dataclass(frozen=True)
class BackendSettings:
    coverbase_mode: str
    coverbase_base_url: str
    coverbase_api_key: str
    coverbase_questionnaire_id: str


settings = BackendSettings(
    coverbase_mode=os.getenv("COVERBASE_MODE", "mock").strip().lower(),
    coverbase_base_url=os.getenv("COVERBASE_BASE_URL", "").strip().rstrip("/"),
    coverbase_api_key=os.getenv("COVERBASE_API_KEY", "").strip(),
    coverbase_questionnaire_id=os.getenv("COVERBASE_QUESTIONNAIRE_ID", "").strip(),
)


def _source_hint() -> str:
    return (
        f"{BACKEND_ENV_PATH}" if DOTENV_LOADED else "the environment (app.yaml env:)"
    )


def validate_backend_settings() -> None:
    if settings.coverbase_mode not in {"mock", "live"}:
        raise RuntimeError("COVERBASE_MODE must be either 'mock' or 'live'.")
    if not settings.coverbase_base_url:
        raise RuntimeError(f"COVERBASE_BASE_URL is missing from {_source_hint()}.")
    if settings.coverbase_mode == "live" and not settings.coverbase_api_key:
        raise RuntimeError(
            "COVERBASE_MODE=live requires COVERBASE_API_KEY in "
            f"{_source_hint()}. Add the key and restart."
        )
