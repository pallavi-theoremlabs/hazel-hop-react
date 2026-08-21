# Render deployment settings

The public web and member portal are separate Vite static sites. Both call the
existing `hazel-hop-react` BFF; neither browser bundle calls Databricks directly.
The BFF remains a single manually managed Render web service.

## Public web static site

- Service: `frontend-hop`
- Root Directory: `apps/public-web`
- Build Command: `npm install && npm run build`
- Publish Directory: `dist`
- `VITE_API_BASE_URL=https://hazel-hop-react.onrender.com`
- `VITE_MEMBER_PORTAL_URL=https://member-portal-c4k9.onrender.com`
- `VITE_HAZEL_ENVIRONMENT=production`
- `VITE_DEV_MODE=false`

Add this Redirect/Rewrite rule in the Render dashboard so BrowserRouter routes
survive direct navigation and refresh:

- Source: `/*`
- Destination: `/index.html`
- Action: `Rewrite`

## Member portal static site

- Service: `member-portal-c4k9`
- Root Directory: `apps/member-portal`
- Build Command: `npm install && npm run build`
- Publish Directory: `dist`
- `VITE_API_BASE_URL=https://hazel-hop-react.onrender.com`
- `VITE_HAZEL_ENVIRONMENT=production`
- `VITE_DEV_MODE=false`

Add the same Render rewrite (`/*` to `/index.html`) for `/create-account`,
`/sign-in`, and `/case/:caseId/*` direct navigation.

## Shared BFF web service

The service stays rooted at `apps/bff`. Keep its current Databricks host, app URL,
OAuth client credentials, and matching `HAZEL_PROXY_KEY`. Set:

- `FRONTEND_ORIGINS=https://frontend-hop.onrender.com,https://member-portal-c4k9.onrender.com`
- `HAZEL_ENVIRONMENT=production`
- `HAZEL_DEV_MODE=false`

`FRONTEND_ORIGIN` is accepted only as a backward-compatible fallback. Do not set
either origin setting to `*`. A separate development/test BFF may enable the
temporary bridge only with both `HAZEL_ENVIRONMENT=development` (or `test`) and
`HAZEL_DEV_MODE=true`; the production BFF must not.

## Temporary Render onboarding test

This is a test-environment configuration, not authentication. It carries the
real case and institution identifiers from an eligible inquiry through the
existing three-route server allowlist. It creates no user session or token.

Temporarily set the public static site to:

- `VITE_API_BASE_URL=https://hazel-hop-react.onrender.com`
- `VITE_MEMBER_PORTAL_URL=https://member-portal-c4k9.onrender.com`
- `VITE_HAZEL_ENVIRONMENT=test`
- `VITE_DEV_MODE=true`

Temporarily set the member static site to:

- `VITE_API_BASE_URL=https://hazel-hop-react.onrender.com`
- `VITE_HAZEL_ENVIRONMENT=test`
- `VITE_DEV_MODE=true`

Temporarily set the BFF to:

- `FRONTEND_ORIGINS=https://frontend-hop.onrender.com,https://member-portal-c4k9.onrender.com`
- `HAZEL_ENVIRONMENT=test`
- `HAZEL_DEV_MODE=true`

The Databricks App must independently set `HAZEL_ENVIRONMENT=test` and
`HAZEL_DEV_MODE=true`. For a real Coverbase call it must also have
`COVERBASE_MODE=live`, its existing `COVERBASE_BASE_URL`, a real
`COVERBASE_QUESTIONNAIRE_ID`, and the `COVERBASE_API_KEY` secret resource.

After testing, rebuild both static sites with `VITE_HAZEL_ENVIRONMENT=production`
and `VITE_DEV_MODE=false`, and restore both servers to
`HAZEL_ENVIRONMENT=production` and `HAZEL_DEV_MODE=false` before redeploying.
