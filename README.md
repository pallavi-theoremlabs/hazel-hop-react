# Hazel HOP React MVP

A lightweight local implementation of the approved Hazel member-onboarding experience. React owns the member interface, FastAPI owns the API boundary and workflow, SQLite provides temporary persistence, and Coverbase is accessed only through a server-side adapter.

The original prototype at `/Users/pallavi/hazel-onboarding` is reference material only and is not modified by this project.

## Structure

```text
hazel-hop-react/
├── frontend/                 React, Vite, React Router, plain Hazel CSS
│   └── src/
│       ├── components/      Shell, tracker, cards, buttons, fields, statuses
│       ├── pages/           Six member onboarding stages
│       ├── services/api.js  Hazel API client
│       └── styles/          Prototype-derived visual system
└── backend/                 FastAPI, SQLite, uploads, Coverbase adapter
    └── app/
        ├── routers/         Hazel-owned API routes
        ├── schemas/         Request schemas
        ├── services/        Coverbase boundary
        └── models/          Domain-model package placeholder
```

## Run locally

Backend:

```bash
cd /Users/pallavi/hazel-hop-react/backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Frontend, in a second terminal:

```bash
cd /Users/pallavi/hazel-hop-react/frontend
npm install
npm run dev
```

Open `http://localhost:5173/submit-interest` for the preferred fresh local test flow. The Developer Test Controls remain available inside a case when `VITE_DEV_MODE=true`.

## Environment

Copy `backend/.env.example` to `backend/.env`.

- `COVERBASE_MODE=mock` runs the full journey with realistic synthetic session data and no credential.
- `COVERBASE_MODE=live` calls the verified Coverbase intake workflow at `COVERBASE_BASE_URL` with the API key as an HTTPS bearer token.
- `COVERBASE_API_KEY` remains server-side and must never be exposed through Vite variables.
- `COVERBASE_QUESTIONNAIRE_ID` defaults to the Hazel Partner Inherent Risk Questionnaire.
- `DATABASE_PATH`, `UPLOAD_DIR`, and `FRONTEND_ORIGIN` can override local defaults.
- `HAZEL_DEV_MODE=true` enables synthetic Hazel Review clarification creation for `HAZEL-TEST-*` cases. Keep it `false` outside local development.

The frontend can optionally set `VITE_API_BASE_URL`; it defaults to `http://localhost:8000`.

## Workflow and gates

Hazel—not Coverbase—owns the staged workflow:

```text
NDA_ACCEPTED
→ INSTITUTION_PROFILE
→ DOCUMENTS
→ DUE_DILIGENCE
→ RISK_QUESTIONS
→ HAZEL_REVIEW
```

The seeded synthetic case starts on NDA. Every transition is persisted in SQLite and guarded in both the React router and FastAPI routes. The member journey is NDA → Due Diligence → Documents → Risk Questions → Hazel Review. The Due Diligence screen uses the backward-compatible `institution-profile` API contract; saving it never starts a second Coverbase intake.

Coverbase-generated answers remain suggestions. Member edits and confirmations are stored in Hazel's `risk_answers` table, separately from provider session data. The member-facing review page omits raw scores, internal weights, private notes, and operator-only reasoning.

Uploaded files are validated for extension and 25 MB size, assigned server-generated names, saved under `backend/uploads`, and indexed in SQLite. The required document is the board-approved BSA/AML/OFAC policy; Wolfsberg CBDDQ and other documents are optional.

## API overview

The backend exposes the public Hazel inquiry endpoint at `/api/public/submit-interest`, followed by case, NDA acceptance, Due Diligence (through the compatible `institution-profile` endpoints), Documents, Coverbase intake, Risk Questions, member answer, and submission endpoints under `/api/cases/{case_id}`. Legacy `/due-diligence` endpoints remain available for existing cases but are no longer a separate member-facing step. Interactive API documentation is available at `http://localhost:8000/docs`.

## Hazel Review clarification boundary

Hazel Review clarification requests are currently stored in Hazel's local `review_clarifications` table. Coverbase's dashboard appears to implement “Request Clarification” through internal email draft/send calls and optional comment/audit calls; no supported first-class clarification API has been confirmed. Hazel does not call those undocumented endpoints.

The intended future boundary is a supported Coverbase webhook/review event creating or updating a structured Hazel clarification, followed by a supported API for sending the member's Hazel response back to Coverbase. Until that contract exists, submitted clarification responses explicitly report `coverbase_sync_status: pending_integration`.

## Later Databricks mapping

No Databricks dependency is included in this MVP. A later adaptation can map:

- React/FastAPI → Databricks App
- SQLite → Lakebase
- local uploads → Unity Catalog Volumes
- background processing → Lakeflow Jobs
- Coverbase credentials → Databricks-managed secrets/configuration

The current API and service boundaries are intentionally small so those persistence and infrastructure adapters can change without redesigning the member workflow.
