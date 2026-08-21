export function isTestEnvironmentEnabled(environment, devMode) {
  const normalizedEnvironment = String(environment || 'production').trim().toLowerCase()
  const explicitlyEnabled = String(devMode || 'false').trim().toLowerCase() === 'true'
  return ['development', 'test'].includes(normalizedEnvironment) && explicitlyEnabled
}
