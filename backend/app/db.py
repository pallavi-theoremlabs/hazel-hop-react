import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.config import BACKEND_DIR

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(BACKEND_DIR / "hazel_hop.db")))
if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = BACKEND_DIR / DATABASE_PATH

STAGES = [
    "NDA_PENDING",
    "NDA_ACCEPTED",
    "INSTITUTION_PROFILE",
    "DOCUMENTS",
    "DUE_DILIGENCE",
    "RISK_QUESTIONS",
    "HAZEL_REVIEW",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_dict(row):
    return dict(row) if row else None


def init_db():
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS onboarding_cases (
                id TEXT PRIMARY KEY,
                institution_id TEXT NOT NULL,
                current_stage TEXT NOT NULL,
                nda_accepted_at TEXT,
                institution_profile_completed_at TEXT,
                documents_completed_at TEXT,
                due_diligence_completed_at TEXT,
                risk_questions_submitted_at TEXT,
                coverbase_session_id TEXT,
                coverbase_vendor_id TEXT,
                coverbase_status TEXT,
                hazel_review_status TEXT,
                review_status TEXT NOT NULL DEFAULT 'Not started',
                additional_information_required INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS institutions (
                id TEXT PRIMARY KEY,
                legal_name TEXT NOT NULL,
                fdic_certificate TEXT NOT NULL UNIQUE,
                rssd_id TEXT,
                institution_type TEXT NOT NULL,
                registration_contact_email TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rafa_screenings (
                institution_id TEXT PRIMARY KEY REFERENCES institutions(id) ON DELETE CASCADE,
                fdic_certificate TEXT NOT NULL,
                rssd_id TEXT,
                rafa_score REAL NOT NULL,
                rafa_status TEXT NOT NULL,
                rating_label TEXT,
                composite_rating TEXT,
                profile_year TEXT,
                profile_quarter TEXT,
                screened_at TEXT NOT NULL,
                CHECK (rafa_status IN ('accepted', 'rejected'))
            );
            CREATE TABLE IF NOT EXISTS institution_profiles (
                case_id TEXT PRIMARY KEY REFERENCES onboarding_cases(id) ON DELETE CASCADE,
                legal_name TEXT, fdic_certificate_number TEXT, rssd_id TEXT,
                institution_type TEXT, website TEXT, headquarters TEXT,
                admission_type TEXT, international_correspondent_relationships TEXT,
                has_dba TEXT, has_fintech_or_baas_programs TEXT,
                primary_contact_name TEXT, primary_contact_title TEXT,
                primary_contact_email TEXT,
                additional_responses_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS express_interest_submissions (
                case_id TEXT PRIMARY KEY REFERENCES onboarding_cases(id) ON DELETE CASCADE,
                legal_name TEXT, fdic_certificate_number TEXT, rssd_id TEXT,
                institution_type TEXT, website TEXT, headquarters TEXT,
                contact_name TEXT, contact_title TEXT, contact_email TEXT,
                data_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL REFERENCES onboarding_cases(id) ON DELETE CASCADE,
                document_type TEXT NOT NULL, original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL, size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                coverbase_document_id TEXT,
                coverbase_sync_status TEXT NOT NULL DEFAULT 'not_started',
                coverbase_synced_at TEXT,
                coverbase_sync_error TEXT,
                coverbase_sync_details_json TEXT NOT NULL DEFAULT '{}',
                file_sha256 TEXT
            );
            CREATE TABLE IF NOT EXISTS due_diligence (
                case_id TEXT PRIMARY KEY REFERENCES onboarding_cases(id) ON DELETE CASCADE,
                data_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS risk_answers (
                case_id TEXT NOT NULL REFERENCES onboarding_cases(id) ON DELETE CASCADE,
                question_id TEXT NOT NULL, answer TEXT NOT NULL,
                confirmed INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
                PRIMARY KEY (case_id, question_id)
            );
            CREATE TABLE IF NOT EXISTS review_clarifications (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES onboarding_cases(id) ON DELETE CASCADE,
                source TEXT NOT NULL,
                source_reference_id TEXT,
                requested_by TEXT NOT NULL,
                request_text TEXT NOT NULL,
                request_type TEXT NOT NULL DEFAULT 'additional_information',
                question_id TEXT,
                requested_at TEXT NOT NULL,
                due_at TEXT,
                status TEXT NOT NULL,
                member_response TEXT NOT NULL DEFAULT '',
                submitted_at TEXT,
                document_required INTEGER NOT NULL DEFAULT 0,
                document_label TEXT,
                replacement_of_hazel_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
                uploaded_hazel_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
                coverbase_sync_status TEXT NOT NULL DEFAULT 'not_started',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (status IN ('open', 'draft', 'submitted', 'resolved'))
            );
            CREATE INDEX IF NOT EXISTS idx_review_clarifications_case
            ON review_clarifications(case_id, requested_at DESC);
            """
        )
        profile_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(institution_profiles)").fetchall()
        }
        if "additional_responses_json" not in profile_columns:
            conn.execute(
                "ALTER TABLE institution_profiles ADD COLUMN additional_responses_json TEXT NOT NULL DEFAULT '{}'"
            )
        case_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(onboarding_cases)").fetchall()
        }
        if "hazel_review_status" not in case_columns:
            conn.execute("ALTER TABLE onboarding_cases ADD COLUMN hazel_review_status TEXT")
            conn.execute(
                "UPDATE onboarding_cases SET hazel_review_status = review_status "
                "WHERE review_status NOT IN ('', 'Not started')"
            )
        document_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(documents)").fetchall()
        }
        document_migrations = {
            "coverbase_document_id": "TEXT",
            "coverbase_sync_status": "TEXT NOT NULL DEFAULT 'not_started'",
            "coverbase_synced_at": "TEXT",
            "coverbase_sync_error": "TEXT",
            "coverbase_sync_details_json": "TEXT NOT NULL DEFAULT '{}'",
            "file_sha256": "TEXT",
        }
        for column, definition in document_migrations.items():
            if column not in document_columns:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {column} {definition}")
        now = utc_now()
        conn.execute(
            """INSERT OR IGNORE INTO onboarding_cases
            (id, institution_id, current_stage, review_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ("HAZEL-TEST-001", "NORTHSTAR-001", "NDA_PENDING", "Not started", now, now),
        )
        conn.execute(
            """INSERT OR IGNORE INTO institution_profiles
            (case_id, legal_name, fdic_certificate_number, rssd_id, institution_type,
             website, headquarters, admission_type,
             international_correspondent_relationships, has_dba,
             has_fintech_or_baas_programs, primary_contact_name,
             primary_contact_title, primary_contact_email, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("HAZEL-TEST-001", "Northstar Community Bank, N.A.", "12001", "",
             "National bank", "https://northstar.example", "Charlotte, North Carolina",
             "", "", "", "", "Jamie Chen", "Chief Operating Officer",
             "jamie.chen@northstar.example", now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO due_diligence (case_id, data_json, updated_at) VALUES (?, ?, ?)",
            ("HAZEL-TEST-001", json.dumps({"institutionWebsite": "https://northstar.example", "headquarters": "Charlotte, North Carolina"}), now),
        )
        conn.execute(
            """INSERT OR IGNORE INTO express_interest_submissions
            (case_id, legal_name, fdic_certificate_number, rssd_id, institution_type,
             website, headquarters, contact_name, contact_title, contact_email,
             data_json, updated_at)
            SELECT case_id, legal_name, fdic_certificate_number, rssd_id,
                   institution_type, website, headquarters, primary_contact_name,
                   primary_contact_title, primary_contact_email, '{}', updated_at
            FROM institution_profiles WHERE case_id = ?""",
            ("HAZEL-TEST-001",),
        )


def require_case(conn, case_id: str):
    row = conn.execute("SELECT * FROM onboarding_cases WHERE id = ?", (case_id,)).fetchone()
    if not row:
        return None
    return row_dict(row)


def update_stage(conn, case_id: str, stage: str, **fields):
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}")
    current = require_case(conn, case_id)
    effective_stage = stage
    if current and STAGES.index(current["current_stage"]) > STAGES.index(stage):
        effective_stage = current["current_stage"]
    assignments = ["current_stage = ?", "updated_at = ?"]
    values = [effective_stage, utc_now()]
    for key, value in fields.items():
        assignments.append(f"{key} = ?")
        values.append(value)
    values.append(case_id)
    conn.execute(f"UPDATE onboarding_cases SET {', '.join(assignments)} WHERE id = ?", values)
