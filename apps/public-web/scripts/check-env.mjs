/**
 * Fail the build when VITE_API_BASE_URL is not set at all.
 *
 * The value is baked into the bundle at build time. So an unset variable does
 * not fail anywhere — it silently produces a bundle that points every API call
 * at http://localhost:8000, which works perfectly on the machine that built it
 * and is broken for every real user.
 *
 * Unset and empty are different on purpose:
 *
 *   unset  -> build fails (this script)
 *   ""     -> same-origin
 *   "https://<render-bff-host>" -> the BFF this app talks to
 *
 * which is also why api.js uses ?? rather than ||: an empty string is falsy, and
 * || would quietly rewrite a deliberate same-origin build back to localhost.
 *
 * VITE_MEMBER_PORTAL_URL is also required: the production landing page uses it
 * for Sign In, and the explicit development-only bridge uses it for the eligible
 * onboarding handoff.
 */
import { loadEnv } from 'vite'

const mode = process.env.NODE_ENV || 'production'
// '' as the prefix loads every variable, .env files merged with process.env,
// so this sees the value the same way vite build will.
const env = loadEnv(mode, process.cwd(), '')
const value = env.VITE_API_BASE_URL
const deploymentEnvironment = (env.VITE_HAZEL_ENVIRONMENT || '').trim().toLowerCase()
const devMode = (env.VITE_DEV_MODE || '').trim().toLowerCase()

if (value === undefined) {
  console.error(`
VITE_API_BASE_URL is not set, so this build would hardcode http://localhost:8000
into the shipped bundle.

Set it to one of:
  VITE_API_BASE_URL=            same-origin
  VITE_API_BASE_URL=http://localhost:8000    local BFF

Either export it, or put it in apps/public-web/.env.
`)
  process.exit(1)
}

const shown = value === '' ? '(empty -> same-origin)' : value
console.log(`VITE_API_BASE_URL = ${shown}`)

if (!['production', 'development', 'test'].includes(deploymentEnvironment)) {
  console.error('\nVITE_HAZEL_ENVIRONMENT must be production, development, or test.\n')
  process.exit(1)
}
if (!['true', 'false'].includes(devMode)) {
  console.error('\nVITE_DEV_MODE must be explicitly true or false.\n')
  process.exit(1)
}
console.log(`VITE_HAZEL_ENVIRONMENT = ${deploymentEnvironment}`)
console.log(`VITE_DEV_MODE = ${devMode}`)

const memberPortal = env.VITE_MEMBER_PORTAL_URL
if (!memberPortal) {
  console.error('\nVITE_MEMBER_PORTAL_URL is required for member Sign In and onboarding navigation.\n')
  process.exit(1)
}

try {
  const url = new URL(memberPortal)
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('unsupported protocol')
} catch {
  console.error('\nVITE_MEMBER_PORTAL_URL must be an absolute http(s) URL.\n')
  process.exit(1)
}
console.log(`VITE_MEMBER_PORTAL_URL = ${memberPortal}`)
