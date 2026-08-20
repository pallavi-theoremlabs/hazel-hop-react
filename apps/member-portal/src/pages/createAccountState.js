const PASSWORD_TESTS = {
  minLength: (value) => value.length >= 12,
  uppercase: (value) => /[A-Z]/.test(value),
  lowercase: (value) => /[a-z]/.test(value),
  number: (value) => /\d/.test(value),
  symbol: (value) => /[^A-Za-z0-9]/.test(value),
}

export const PASSWORD_REQUIREMENTS = Object.freeze([
  'minLength',
  'uppercase',
  'lowercase',
  'number',
  'symbol',
])

export function passwordRequirementState(password = '') {
  return Object.fromEntries(
    PASSWORD_REQUIREMENTS.map((requirement) => [
      requirement,
      PASSWORD_TESTS[requirement](password),
    ]),
  )
}

export function isPasswordValid(password = '') {
  return Object.values(passwordRequirementState(password)).every(Boolean)
}

export function validateCreateAccount(password = '', confirmation = '') {
  const errors = []

  if (!password) {
    errors.push({ field: 'password', messageKey: 'createAccount.validation.passwordRequired' })
  } else if (!isPasswordValid(password)) {
    errors.push({ field: 'password', messageKey: 'createAccount.validation.summary' })
  }

  if (!confirmation) {
    errors.push({
      field: 'confirmation',
      messageKey: 'createAccount.validation.confirmationRequired',
    })
  } else if (password !== confirmation) {
    errors.push({ field: 'confirmation', messageKey: 'createAccount.validation.mismatch' })
  }

  return errors
}

export function canBeginSubmission(errors, submitting) {
  return !submitting && errors.length === 0
}

export function togglePasswordVisibility(visible) {
  return !visible
}
