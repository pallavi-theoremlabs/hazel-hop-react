import test from 'node:test'
import assert from 'node:assert/strict'

import {
  canBeginSubmission,
  isPasswordValid,
  passwordRequirementState,
  togglePasswordVisibility,
  validateCreateAccount,
} from './createAccountState.js'

test('an empty form reports both required fields', () => {
  assert.deepEqual(validateCreateAccount('', ''), [
    { field: 'password', messageKey: 'createAccount.validation.passwordRequired' },
    {
      field: 'confirmation',
      messageKey: 'createAccount.validation.confirmationRequired',
    },
  ])
})

test('a password shorter than 12 characters is invalid', () => {
  assert.equal(passwordRequirementState('Aa1!short').minLength, false)
  assert.equal(isPasswordValid('Aa1!short'), false)
})

test('each required character class is enforced', () => {
  assert.equal(passwordRequirementState('lowercase123!').uppercase, false)
  assert.equal(passwordRequirementState('UPPERCASE123!').lowercase, false)
  assert.equal(passwordRequirementState('NoNumbersHere!').number, false)
  assert.equal(passwordRequirementState('NoSymbols1234').symbol, false)
})

test('a password satisfying every requirement is valid', () => {
  assert.equal(isPasswordValid('ValidPassword1!'), true)
  assert.deepEqual(validateCreateAccount('ValidPassword1!', 'ValidPassword1!'), [])
})

test('a mismatched confirmation is rejected', () => {
  assert.deepEqual(validateCreateAccount('ValidPassword1!', 'DifferentPassword2!'), [
    { field: 'confirmation', messageKey: 'createAccount.validation.mismatch' },
  ])
})

test('submission cannot begin again while already submitting', () => {
  assert.equal(canBeginSubmission([], false), true)
  assert.equal(canBeginSubmission([], true), false)
  assert.equal(
    canBeginSubmission(
      [{ field: 'password', messageKey: 'createAccount.validation.summary' }],
      false,
    ),
    false,
  )
})

test('password visibility toggles in both directions', () => {
  assert.equal(togglePasswordVisibility(false), true)
  assert.equal(togglePasswordVisibility(true), false)
})
