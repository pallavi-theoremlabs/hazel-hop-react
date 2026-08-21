const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function isUuid(value) {
  return UUID_PATTERN.test(String(value || '').trim())
}

export function integrationInstitutionId(search = '') {
  const value = new URLSearchParams(search).get('institution_id') || ''
  return isUuid(value) ? value : ''
}

export function integrationCasePath(caseId, institutionId, stage = 'overview') {
  if (!isUuid(caseId) || !isUuid(institutionId)) return null
  const parameters = new URLSearchParams({ institution_id: institutionId })
  return `/case/${caseId}/${stage}?${parameters.toString()}`
}
