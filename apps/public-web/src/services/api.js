// Public API client. Two endpoints, both under /api/public — the only two this
// app calls. The member portal keeps its own copy of this module with the
// /api/cases/* surface; the two are deliberately not shared, because they have
// no endpoint in common and sharing them would couple the apps' release cadence
// to gain fifteen lines of fetch wrapper.
//
// request(), jsonOptions() and the error shape below are copied verbatim from
// the combined client so error handling stays identical across both apps.

// ?? not ||: an empty VITE_API_BASE_URL means "same origin". || treats '' as
// falsy and would rewrite that back to localhost, shipping a bundle that sends
// every request to the user's own machine. The unset case is caught at build
// time by scripts/check-env.mjs; the default below is only for `npm run dev`.
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options)
  if (response.status === 204) return null
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = payload.detail
    const message = typeof detail === 'string' ? detail : detail?.message || 'Something went wrong.'
    const error = new Error(message)
    error.status = response.status
    throw error
  }
  return payload
}

const jsonOptions = (method, data) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
})

export const lookupBankByFdic = (fdicCertificateNumber) => request(`/api/public/banks/${encodeURIComponent(fdicCertificateNumber)}`)
export const submitInterest = (data) => request('/api/public/submit-interest', jsonOptions('POST', data))
