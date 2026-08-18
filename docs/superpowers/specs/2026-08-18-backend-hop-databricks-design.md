# Backend-Hop: Databricks App deployment design

Date: 2026-08-18
Status: Approved (pending live Databricks values)

## Goal

Host the Hazel HOP FastAPI backend as a Databricks App, connected to:
- the already-deployed frontend (`Svbongo/Frontend-Hop`, live at `https://frontend-hop.onrender.com`)
- the RAFA API (unchanged, `onrender` provider)
- Databricks Lakebase Postgres (`hazel-hop-lakebase` project, `production` branch) and a Unity Catalog
  Volume (`/Volumes/hazel_hop_test/default/documents`), both already provisioned with a schema matching
  this backend's existing SQLite tables.

## Repo structure

New standalone GitHub repo (`Backend-Hop`, mirroring `Frontend-Hop`): the `backend/` folder from
`pallavi-theoremlabs/hazel-hop-react`'s `main` branch, flattened to repo root, fresh git history —
disconnected from `hazel-hop-react`. Local working copy: this directory.

## Databricks App packaging

- `app.yaml` at repo root:
  ```yaml
  command: ['uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', '8000']
  env:
    - name: FRONTEND_ORIGIN
      value: 'https://frontend-hop.onrender.com'
    - name: UPLOAD_DIR
      value: '/Volumes/hazel_hop_test/default/documents'
    - name: PGDATABASE
      value: 'databricks_postgres'
    - name: PGPORT
      value: '5432'
    - name: PGSSLMODE
      value: 'require'
    - name: PGHOST
      value: '<TODO: from Lakebase Connect modal, Parameters only>'
    - name: PGUSER
      value: '<TODO: this app''s own DATABRICKS_CLIENT_ID, from the app's Environment tab after creation>'
    - name: ENDPOINT_NAME
      value: '<TODO: projects/<project-id>/branches/<branch-id>/endpoints/<endpoint-id>, from Lakebase Computes tab>'
  ```
  The three `TODO` values cannot exist until the Databricks App itself is created (chicken-and-egg: the
  app's service principal client ID is assigned at creation time). See **Deployment prerequisites** below.

- `app/config.py`: currently `raise RuntimeError` if no `.env` file exists on disk at
  `backend/.env`. Databricks Apps injects env vars directly into the process — there is no `.env` file
  in that environment. Fix: load `.env` only if present (dev convenience), never require it; rely on
  real process env vars otherwise.

## Data layer

Verified against current Databricks docs (`docs.databricks.com/aws/en/oltp/projects/tutorial-databricks-apps-autoscaling`,
fetched 2026-08-18): a Databricks App authenticates to Lakebase using its own auto-injected service
principal identity. Pattern:

```python
from databricks.sdk import WorkspaceClient
import psycopg
from psycopg_pool import ConnectionPool

w = WorkspaceClient()

class OAuthConnection(psycopg.Connection):
    @classmethod
    def connect(cls, conninfo='', **kwargs):
        credential = w.postgres.generate_database_credential(
            endpoint=os.environ["ENDPOINT_NAME"]
        )
        kwargs['password'] = credential.token
        return super().connect(conninfo, **kwargs)

pool = ConnectionPool(
    conninfo=f"dbname={os.environ['PGDATABASE']} user={os.environ['PGUSER']} "
             f"host={os.environ['PGHOST']} port={os.environ.get('PGPORT','5432')} "
             f"sslmode={os.environ.get('PGSSLMODE','require')}",
    connection_class=OAuthConnection,
    min_size=1, max_size=10, open=True,
)
```

Tokens (workspace OAuth + database credential) expire after 60 minutes; the connection pool mints a
fresh one per new connection, so no manual refresh loop is needed.

**Approach chosen (dialect shim, not an ORM rewrite):** Keep every existing `?`-placeholder SQL query in
`db.py` / `routers/cases.py` / `routers/public.py` / `routers/dev.py` unchanged. Add a thin wrapper that:
- translates `?` → `%s` before handing queries to psycopg (SQLite mode is untouched — still raw `sqlite3`)
- yields a pooled psycopg connection from `connection()` when `PGHOST` is set in the environment, else
  today's `sqlite3.connect(DATABASE_PATH)` unchanged
- skips the SQLite `CREATE TABLE IF NOT EXISTS` / seed-data block in `init_db()` entirely when running
  in Postgres mode — the 9 tables (`onboarding_cases`, `institutions`, `rafa_screenings`,
  `institution_profiles`, `express_interest_submissions`, `documents`, `due_diligence`, `risk_answers`,
  `review_clarifications`) already exist in Lakebase with a matching schema.

Rejected alternative: rewrite the data layer on an ORM (e.g. SQLAlchemy) for a more formal dual-backend
abstraction. More correct long-term, but a much larger rewrite/risk for an MVP with working, tested
SQLite code. YAGNI.

New dependencies (`requirements.txt`): `psycopg[binary]`, `psycopg-pool`, `databricks-sdk`.

## Document storage

`UPLOAD_DIR` is already env-configurable and used via plain `Path`/file I/O in `routers/cases.py`. Unity
Catalog Volumes mount as normal filesystem paths inside Databricks compute, so this is pure
configuration — set `UPLOAD_DIR=/Volumes/hazel_hop_test/default/documents`. No code change. Requires the
app's service principal to have read/write grants on that volume (infra step, not code).

## Frontend connection

`FRONTEND_ORIGIN` env var already drives the FastAPI CORS middleware — set to
`https://frontend-hop.onrender.com`. Separately (out of scope for this repo): once the backend has a
live Databricks Apps URL, `Frontend-Hop`'s deployed `VITE_API_BASE_URL` needs updating and redeploying to
point at it.

## RAFA

No code changes. Provider stays `onrender` (existing `bank-profile-proxy.onrender.com`, unchanged from
today's `.env.example` default). The `databricks` RAFA provider code path in `services/rafa.py` is
unrelated to this work — it's for a hypothetical separate Databricks-hosted RAFA service, not for this
backend's own database connectivity.

## Deployment prerequisites (user-side, outside this repo's code)

0. **Workspace is confirmed Databricks Free Edition** — the workspace UI literally shows "Free Edition"
   in the product logo (screenshot-confirmed 2026-08-18). It's a personal Free Edition account tied to
   the user's company email (`@theoremlabs.io`), not a business/enterprise workspace — an earlier
   attempt to infer this from the presence of Workspace admin settings sections was wrong and got
   corrected. This has real constraints:
   - **Apps auto-stop after 24 hours** of being started/updated/redeployed, then need a manual restart —
     this backend will not stay up indefinitely unattended.
   - **Outbound internet access is restricted to a limited set of trusted domains** unless the account
     completes **LinkedIn verification**. Without it, the backend's calls to
     `bank-profile-proxy.onrender.com` (RAFA) and `api.coverbase.app` (Coverbase) may be blocked
     outright. A "Verify with LinkedIn" option was not found under Settings → Profile or Linked accounts
     for this account — per Databricks docs the option only appears "if you're eligible," so it may live
     elsewhere or not be offered to this account. **Decision: don't block on finding it — create the app
     and empirically test whether it can reach `bank-profile-proxy.onrender.com` and `api.coverbase.app`
     once deployed. If blocked, revisit LinkedIn verification or an egress workaround then.**
   - Up to 3 Databricks Apps per account; one Lakebase project per account (scale-to-zero compute — first
     query after idle may have brief cold-start latency).
   - Source: [Free Edition limitations](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations),
     fetched 2026-08-18.
1. Create the Databricks App (empty, so it's assigned a service principal / `DATABRICKS_CLIENT_ID`).
2. From the Lakebase project's **Connect** modal (Parameters only), get `PGHOST` and confirm
   `PGDATABASE`.
3. From the Lakebase branch's **Computes** tab, copy the endpoint resource name for `ENDPOINT_NAME`.
4. In the Lakebase SQL editor, run once:
   ```sql
   CREATE EXTENSION IF NOT EXISTS databricks_auth;
   SELECT databricks_create_role('<this app's DATABRICKS_CLIENT_ID>', 'service_principal');
   GRANT CONNECT ON DATABASE databricks_postgres TO "<DATABRICKS_CLIENT_ID>";
   GRANT CREATE, USAGE ON SCHEMA public TO "<DATABRICKS_CLIENT_ID>";
   ```
5. Grant the app's service principal read/write on the `/Volumes/hazel_hop_test/default/documents` UC
   Volume.
6. Fill the three `TODO` values into `app.yaml` and deploy.
7. Update and redeploy `Frontend-Hop` with the new backend's `VITE_API_BASE_URL`.

## Testing

Existing `tests/test_rafa.py` and `tests/test_submit_interest_rafa.py` are unaffected (RAFA unchanged).
Add a test for the dialect shim (`?`→`%s` translation) run against SQLite only — no live Postgres
integration test in this repo, since Lakebase credentials aren't available in a local/CI environment.
