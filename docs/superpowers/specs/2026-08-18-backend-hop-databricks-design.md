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

**Superseded (2026-08-18):** originally planned as a standalone repo mirroring `Frontend-Hop`. After
back-and-forth, landed instead on a branch: `Backend_Hop`, pushed to the existing
`pallavi-theoremlabs/hazel-hop-react` repo, sitting independently alongside `main` (disconnected git
history — pushed from this directory's own local history, not derived from `main` via a flatten commit
the way `frontend-deployment` was built). Content: the `backend/` folder from `hazel-hop-react`'s `main`,
flattened to repo root. Local working copy: this directory, remote `origin` → `hazel-hop-react.git`.
The Databricks App (`backendhop`) is Git-linked directly to this branch.

## Databricks App packaging

**Superseded finding (2026-08-18, after the app already existed):** the app itself already provides
`DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`, and `DATABRICKS_APP_PORT` as
default env vars automatically (per
[Databricks Apps environment](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/system-env)) —
no need to manually copy the client ID into `app.yaml` at all. And Databricks Apps' **resources** feature
(attach via UI, reference via `valueFrom` in `app.yaml`) replaces the manual SQL grant and manual UC
Volume permission steps from the original draft of this doc — see **Deployment prerequisites** below for
the corrected, much shorter list.

- `app.yaml` at repo root (implemented, values filled in):
  ```yaml
  command: ['sh', '-c', 'uvicorn app.main:app --host 0.0.0.0 --port $DATABRICKS_APP_PORT']
  env:
    - name: FRONTEND_ORIGIN
      value: 'https://frontend-hop.onrender.com'
    - name: UPLOAD_DIR
      value: '/Volumes/hazel_hop_test/default/documents'
    - name: COVERBASE_BASE_URL
      value: 'https://api.coverbase.app'
    - name: RAFA_BASE_URL
      value: 'https://bank-profile-proxy.onrender.com'
    - name: RAFA_PROVIDER
      value: 'onrender'
    - name: PGDATABASE
      value: 'databricks_postgres'
    - name: PGPORT
      value: '5432'
    - name: PGSSLMODE
      value: 'require'
    - name: PGHOST
      value: 'ep-plain-poetry-d8kyapm8.database.us-east-2.cloud.databricks.com'
    - name: ENDPOINT_NAME
      valueFrom: database   # the Database app resource's actual key, not the "postgres" default
  ```
  `PGUSER` is not set in `app.yaml` at all — the code reads it directly from the auto-provided
  `DATABRICKS_CLIENT_ID` (see Data layer below), since that's exactly the value Databricks uses as the
  Postgres role name when the Database resource is attached.

  The `command` doesn't use Databricks' documented `DATABRICKS_APP_PORT` command-substitution feature
  directly, because the docs don't state its exact token syntax (`$VAR`, `${VAR}`, etc.) and guessing
  wrong would mean the app fails to bind with no clear error. Instead, `sh -c '...'` invokes a real shell
  that expands `$DATABRICKS_APP_PORT` from the process environment — that variable is documented as a
  normal default env var regardless, so this sidesteps the ambiguity entirely.

  `COVERBASE_MODE` and `COVERBASE_API_KEY` are deliberately absent — `config.py` already defaults
  `COVERBASE_MODE` to `mock`, which needs no key, so the first deploy doesn't depend on the still-unsolved
  secret-scope question (see Deployment prerequisites). Live Coverbase mode can be switched on later once
  a secret resource is wired up.

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

# PGUSER is deliberately not an app.yaml env var — Databricks names the Postgres role after
# DATABRICKS_CLIENT_ID when the Database resource is attached, and that var is auto-provided.
pool = ConnectionPool(
    conninfo=f"dbname={os.environ['PGDATABASE']} user={os.environ['DATABRICKS_CLIENT_ID']} "
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
configuration — set `UPLOAD_DIR=/Volumes/hazel_hop_test/default/documents`. No code change. The app's
service principal needs read/write on that volume — granted by attaching it as a **Volume** app resource
in the UI (see Deployment prerequisites), not via manual SQL/UI permission editing.

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
1. ~~Create the Databricks App~~ — **done**: app `backendhop` exists, Git-linked directly to this repo's
   `Backend_Hop` branch (App ID `abcafad5-0ac7-4b05-9cfa-f7c205...931a`).
2. In the app's **Edit** view, **App resources** section, **+ Add resource**:
   - **Database** → select the `hazel-hop-lakebase` project/branch → permission **Can connect and
     create** → keep default key `postgres`. This single step replaces the old manual SQL grant entirely
     — per Databricks docs, attaching a Database resource makes Databricks create the Postgres role
     (named after the app's `DATABRICKS_CLIENT_ID`) and grant it `CONNECT`/`CREATE` automatically.
   - **Volume** → select the `hazel_hop_test.default.documents` UC Volume → permission **Can read and
     write**. This replaces the old manual volume-permission step.
   - **Secret** (deferred — see below) for `COVERBASE_API_KEY` (and `RAFA_API_KEY` if the code ever
     requires one for the `onrender` provider — currently it doesn't strictly validate its presence).
     Requires an existing secret scope; **no Databricks CLI is available in this session to create one**,
     and Free Edition's UI location for secret-scope creation hasn't been confirmed. Two options: (a) the
     user creates a scope via `databricks secrets create-scope`/`put-secret` if they have the CLI
     available on their own machine, or (b) ship the first deploy with `COVERBASE_MODE=mock` (no secret
     needed) and wire the live key in once a scope exists.
3. ~~Get `PGHOST`~~ — **done**: `ep-plain-poetry-d8kyapm8.database.us-east-2.cloud.databricks.com`
   (from the Lakebase Connect modal, Parameters only view).
4. ~~Fill `PGHOST` into `app.yaml`~~ — **done**, along with `config.py`'s `.env`-required-file fix, the
   `db.py` Postgres/SQLite dialect shim, the `cursor.lastrowid` → `RETURNING id` fix in
   `routers/cases.py` (psycopg has no `lastrowid`), and `requirements.txt` additions
   (`databricks-sdk`, `psycopg[binary]`, `psycopg-pool`). Pushed to `Backend_Hop`.
5. **Remaining:** redeploy the app in the Databricks UI (it's Git-linked to `Backend_Hop`, so it should
   pick up the new commits — may need a manual "Deploy" click or a sync step).
6. **Remaining:** update and redeploy `Frontend-Hop` with the new backend's `VITE_API_BASE_URL`, once the
   app has a live, working URL (`https://backendhop-747....databricksapps.com`, full URL still needed).
7. **Still open:** the `COVERBASE_API_KEY` secret question from step 2 above — first deploy ships with
   `COVERBASE_MODE=mock` (config.py's default) to avoid depending on it.

## Testing

Existing `tests/test_rafa.py` and `tests/test_submit_interest_rafa.py` are unaffected (RAFA unchanged).
Add a test for the dialect shim (`?`→`%s` translation) run against SQLite only — no live Postgres
integration test in this repo, since Lakebase credentials aren't available in a local/CI environment.
