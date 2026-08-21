const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function testOnboardingDestination(search = '') {
  const parameters = new URLSearchParams(search)
  const caseId = parameters.get('case_id') || ''
  const institutionId = parameters.get('dev_institution_id') || ''
  const nextPath = parameters.get('next_path') || ''

  if (!UUID_PATTERN.test(caseId) || !UUID_PATTERN.test(institutionId)) return null

  const expectedPath = `/case/${caseId}/nda`
  if (nextPath !== expectedPath) return null

  const destinationParameters = new URLSearchParams({
    dev_institution_id: institutionId,
  })
  return `${expectedPath}?${destinationParameters.toString()}`
}
