export function buildMemberPortalUrl(baseUrl, path, parameters = {}) {
  const normalizedBase = baseUrl?.trim().replace(/\/+$/, '')
  if (!normalizedBase) throw new Error('VITE_MEMBER_PORTAL_URL is required')

  const url = new URL(path, `${normalizedBase}/`)
  for (const [name, value] of Object.entries(parameters)) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(name, value)
    }
  }
  return url.toString()
}
