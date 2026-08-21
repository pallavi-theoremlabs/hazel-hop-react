// ?? not ||: an empty VITE_API_BASE_URL means "same origin", which is what the
// Databricks Apps deploy uses. || treats '' as falsy and would rewrite that back
// to localhost, shipping a bundle that sends every request to the user's own
// machine. The unset case is caught at build time by scripts/check-env.mjs; the
// default below is only for `npm run dev`.
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const DEV_MODE = import.meta.env.DEV && import.meta.env.VITE_DEV_MODE === 'true'
const DEV_CONTEXT_KEY = 'hazel.dev.institution_id'

function developmentInstitutionId() {
  if (!DEV_MODE) return ''
  const fromHandoff = new URLSearchParams(window.location.search).get('dev_institution_id') || ''
  if (fromHandoff) sessionStorage.setItem(DEV_CONTEXT_KEY, fromHandoff)
  return fromHandoff || sessionStorage.getItem(DEV_CONTEXT_KEY) || ''
}

async function request(path, options = {}) {
  const devInstitutionId = developmentInstitutionId()
  const headers = new Headers(options.headers || {})
  if (devInstitutionId) headers.set('X-Hazel-Dev-Institution-Id', devInstitutionId)
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
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

export const getCase = (caseId) => request(`/api/cases/${caseId}`)
export const lookupBankByFdic = (fdicCertificateNumber) => request(`/api/banks/${encodeURIComponent(fdicCertificateNumber)}`)
export const submitInterest = (data) => request('/api/submit-interest', jsonOptions('POST', data))
export const createDevCase = (data) => request('/api/dev/create-case', jsonOptions('POST', data))
export const resetDevCase = (caseId) => request(`/api/dev/reset-case/${caseId}`, { method: 'POST' })
export const createDevClarification = (caseId, data) => request(`/api/dev/cases/${caseId}/hazel-review/clarification`, jsonOptions('POST', data))
export const acceptNda = (caseId) => request(`/api/cases/${caseId}/nda/accept`, { method: 'POST' })
export const createCoverbaseSession = (caseId) => request(`/api/cases/${caseId}/coverbase/session`, { method: 'POST' })
export const getInstitutionProfile = (caseId) => request(`/api/cases/${caseId}/institution-profile`)
export const getInstitutionProfileSchema = (caseId) => request(`/api/cases/${caseId}/institution-profile/schema`)
export const saveInstitutionProfile = (caseId, data) => request(`/api/cases/${caseId}/institution-profile`, jsonOptions('PUT', data))
export const getInstitutionProfileQuestions = (caseId) => request(`/api/cases/${caseId}/institution-profile/questions`)
export const saveInstitutionProfileResponses = (caseId, responses) => request(`/api/cases/${caseId}/institution-profile/responses`, jsonOptions('POST', { responses }))
export const completeInstitutionProfile = (caseId) => request(`/api/cases/${caseId}/institution-profile/complete`, { method: 'POST' })
export const getDocuments = (caseId) => request(`/api/cases/${caseId}/documents`)
export function uploadDocument(caseId, file, documentType) {
  const body = new FormData()
  body.append('file', file)
  body.append('document_type', documentType)
  return request(`/api/cases/${caseId}/documents`, { method: 'POST', body })
}
export const deleteDocument = (caseId, documentId) => request(`/api/cases/${caseId}/documents/${documentId}`, { method: 'DELETE' })
export const retryDocumentCoverbaseSync = (caseId, documentId) => request(`/api/cases/${caseId}/documents/${documentId}/coverbase-sync`, { method: 'POST' })
export const completeDocuments = (caseId) => request(`/api/cases/${caseId}/documents/complete`, { method: 'POST' })
export const getDueDiligence = (caseId) => request(`/api/cases/${caseId}/due-diligence`)
export const saveDueDiligence = (caseId, data) => request(`/api/cases/${caseId}/due-diligence`, jsonOptions('PUT', { data }))
export const completeDueDiligence = (caseId) => request(`/api/cases/${caseId}/due-diligence/complete`, { method: 'POST' })
export const startCoverbaseIntake = (caseId) => request(`/api/cases/${caseId}/coverbase/intake`, { method: 'POST' })
export const getCoverbaseIntake = (caseId) => request(`/api/cases/${caseId}/coverbase/intake`)
export const getRiskQuestions = (caseId) => request(`/api/cases/${caseId}/risk-questions`)
export const saveRiskAnswer = (caseId, questionId, response) => request(`/api/cases/${caseId}/risk-questions/${questionId}`, jsonOptions('POST', response))
export const submitRiskQuestions = (caseId) => request(`/api/cases/${caseId}/risk-questions/submit`, { method: 'POST' })
export const getHazelReview = (caseId) => request(`/api/cases/${caseId}/hazel-review`)
export const getHazelReviewStatus = (caseId) => request(`/api/cases/${caseId}/hazel-review/status`)
export const saveClarificationDraft = (caseId, clarificationId, response) => request(`/api/cases/${caseId}/hazel-review/clarifications/${clarificationId}/draft`, jsonOptions('POST', { response }))
export const submitClarificationResponse = (caseId, clarificationId) => request(`/api/cases/${caseId}/hazel-review/clarifications/${clarificationId}/submit`, { method: 'POST' })
export function uploadClarificationDocument(caseId, clarificationId, file) {
  const body = new FormData()
  body.append('file', file)
  return request(`/api/cases/${caseId}/hazel-review/clarifications/${clarificationId}/document`, { method: 'POST', body })
}
