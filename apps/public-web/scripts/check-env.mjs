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
 * VITE_MEMBER_PORTAL_URL is deliberately NOT required. It is read only behind
 * DEV_MODE (import.meta.env.DEV && VITE_DEV_MODE), so a production build strips
 * its only caller; requiring it would fail builds over a value production never
 * reads. It is reported below when set, so a dev build shows where the handoff
 * points.
 */
import { loadEnv } from 'vite'

const mode = process.env.NODE_ENV || 'production'
// '' as the prefix loads every variable, .env files merged with process.env,
// so this sees the value the same way vite build will.
const env = loadEnv(mode, process.cwd(), '')
const value = env.VITE_API_BASE_URL

if (value === undefined) {
  console.error(`
VITE_API_BASE_URL is not set, so this build would hardcode http://localhost:8000
into the shipped bundle.

Set it to one of:
  VITE_API_BASE_URL=            same-origin
  VITE_API_BASE_URL=http://localhost:8000    local backend

Either export it, or put it in apps/public-web/.env.
`)
  process.exit(1)
}

const shown = value === '' ? '(empty -> same-origin)' : value
console.log(`VITE_API_BASE_URL = ${shown}`)

const memberPortal = env.VITE_MEMBER_PORTAL_URL
if (memberPortal) {
  console.log(`VITE_MEMBER_PORTAL_URL = ${memberPortal} (dev-only handoff)`)
}
