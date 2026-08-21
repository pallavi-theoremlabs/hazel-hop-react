# Render deployment settings

This repository is currently configured as a throwaway integration application.
The public web and member portal are separate Vite static sites, both calling the
same Render BFF. The BFF is the only caller of the Databricks App.

There is no end-user authentication in this deployment. An eligible Submit
Interest response carries its real `case_id` and `institution_id` directly into
the member portal. The BFF accepts that integration context only for case load,
NDA acceptance and Coverbase session creation, then establishes the existing
Lakebase RLS context.

## Public web static site

- Service: `frontend-hop`
- Root Directory: `apps/public-web`
- Build Command: `npm install && npm run build`
- Publish Directory: `dist`
- `VITE_API_BASE_URL=https://hazel-hop-react.onrender.com`
- `VITE_MEMBER_PORTAL_URL=https://member-portal-c4k9.onrender.com`

Add this Render Redirect/Rewrite rule:

- Source: `/*`
- Destination: `/index.html`
- Action: `Rewrite`

## Member portal static site

- Service: `member-portal-c4k9`
- Root Directory: `apps/member-portal`
- Build Command: `npm install && npm run build`
- Publish Directory: `dist`
- `VITE_API_BASE_URL=https://hazel-hop-react.onrender.com`

Add the same Render rewrite (`/*` to `/index.html`) so direct real-case URLs and
refreshes are handled by React Router.

The member root provides a small integration form for reopening a known real
case. The normal path does not require it:

`Submit Interest -> /case/{case_id}/nda?institution_id={institution_id}`

## Shared BFF web service

Keep the existing service rooted at `apps/bff`, with:

- `FRONTEND_ORIGINS=https://frontend-hop.onrender.com,https://member-portal-c4k9.onrender.com`
- existing `DATABRICKS_HOST`
- existing `DATABRICKS_APP_URL`
- existing `DATABRICKS_CLIENT_ID`
- existing `DATABRICKS_CLIENT_SECRET`
- existing `HAZEL_PROXY_KEY`

`HAZEL_ENVIRONMENT` and `HAZEL_DEV_MODE` are not used by the integration flow.
Do not create a second BFF.

## Databricks App

The App no longer needs `HAZEL_ENVIRONMENT` or `HAZEL_DEV_MODE` for the three
canonical onboarding routes. Keep the existing Lakebase resource and matching
`HAZEL_PROXY_KEY`.

For a real Coverbase integration call, configure:

- `COVERBASE_MODE=live`
- `COVERBASE_BASE_URL=https://api.coverbase.app`
- a real `COVERBASE_QUESTIONNAIRE_ID`
- `COVERBASE_API_KEY` through the attached `coverbase-api-key` secret resource

The supported integration slice remains exactly:

- `GET /api/cases/{case_id}`
- `POST /api/cases/{case_id}/nda/accept`
- `POST /api/cases/{case_id}/coverbase/session`

All other legacy case routers remain parked. The schema remains the canonical
`institution`, `"user"`, `rafa`, `onboarding_case`, `document`,
`case_stage_transition`, and `audit_log` schema.
