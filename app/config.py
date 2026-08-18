"""Backend-only configuration loaded from the backend project's .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
BACKEND_ENV_PATH = BACKEND_DIR / ".env"

if not BACKEND_ENV_PATH.is_file():
    raise RuntimeError(f"Backend environment file not found: {BACKEND_ENV_PATH}")

# This path is anchored to this module, so loading never depends on the shell's
# current working directory. Existing process-level environment variables retain
# precedence, which is the expected behavior for deployed environments.
DOTENV_LOADED = load_dotenv(dotenv_path=BACKEND_ENV_PATH, override=False)


@dataclass(frozen=True)
class BackendSettings:
    coverbase_mode: str
    coverbase_base_url: str
    coverbase_api_key: str
    coverbase_questionnaire_id: str
    rafa_base_url: str
    rafa_api_key: str
    rafa_eligibility_min_score: float
    rafa_provider: str
    databricks_host: str
    databricks_client_id: str
    databricks_client_secret: str
    databricks_app_url: str


settings = BackendSettings(
    coverbase_mode=os.getenv("COVERBASE_MODE", "mock").strip().lower(),
    coverbase_base_url=os.getenv("COVERBASE_BASE_URL", "").strip().rstrip("/"),
    coverbase_api_key=os.getenv("COVERBASE_API_KEY", "").strip(),
    coverbase_questionnaire_id=os.getenv("COVERBASE_QUESTIONNAIRE_ID", "").strip(),
    rafa_base_url=os.getenv("RAFA_BASE_URL", "").strip().rstrip("/"),
    rafa_api_key=os.getenv("RAFA_API_KEY", "").strip(),
    rafa_eligibility_min_score=float(
        os.getenv("RAFA_ELIGIBILITY_MIN_SCORE", "1").strip()
    ),
    rafa_provider=os.getenv("RAFA_PROVIDER", "onrender").strip().lower(),
    databricks_host=os.getenv("DATABRICKS_HOST", "").strip().rstrip("/"),
    databricks_client_id=os.getenv("DATABRICKS_CLIENT_ID", "").strip(),
    databricks_client_secret=os.getenv("DATABRICKS_CLIENT_SECRET", "").strip(),
    databricks_app_url=os.getenv("DATABRICKS_APP_URL", "").strip().rstrip("/"),
)


def validate_backend_settings() -> None:
    if settings.coverbase_mode not in {"mock", "live"}:
        raise RuntimeError("COVERBASE_MODE must be either 'mock' or 'live'.")
    if not settings.coverbase_base_url:
        raise RuntimeError(f"COVERBASE_BASE_URL is missing from {BACKEND_ENV_PATH}.")
    if settings.coverbase_mode == "live" and not settings.coverbase_api_key:
        raise RuntimeError(
            "COVERBASE_MODE=live requires COVERBASE_API_KEY in "
            f"{BACKEND_ENV_PATH}. Add the key and restart FastAPI."
        )
    if settings.rafa_eligibility_min_score < 0:
        raise RuntimeError("RAFA_ELIGIBILITY_MIN_SCORE must be zero or greater.")
    if settings.rafa_provider not in {"onrender", "databricks"}:
        raise RuntimeError("RAFA_PROVIDER must be either 'onrender' or 'databricks'.")
    if settings.rafa_provider == "databricks":
        missing = [
            name
            for name, value in (
                ("DATABRICKS_HOST", settings.databricks_host),
                ("DATABRICKS_CLIENT_ID", settings.databricks_client_id),
                ("DATABRICKS_CLIENT_SECRET", settings.databricks_client_secret),
                ("DATABRICKS_APP_URL", settings.databricks_app_url),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "RAFA_PROVIDER=databricks requires backend configuration: "
                + ", ".join(missing)
            )
