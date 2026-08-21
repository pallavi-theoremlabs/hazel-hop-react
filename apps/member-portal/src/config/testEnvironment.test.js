import assert from 'node:assert/strict'
import test from 'node:test'

import { isTestEnvironmentEnabled } from './testEnvironment.js'

test('enables test-only behavior only when both gates are open', () => {
  assert.equal(isTestEnvironmentEnabled('development', 'true'), true)
  assert.equal(isTestEnvironmentEnabled('test', 'true'), true)
})

test('keeps production closed regardless of the dev flag', () => {
  assert.equal(isTestEnvironmentEnabled('production', 'true'), false)
  assert.equal(isTestEnvironmentEnabled('production', 'false'), false)
})

test('keeps test closed when the explicit dev flag is false', () => {
  assert.equal(isTestEnvironmentEnabled('test', 'false'), false)
})

test('defaults closed for missing or unknown values', () => {
  assert.equal(isTestEnvironmentEnabled(undefined, undefined), false)
  assert.equal(isTestEnvironmentEnabled('staging', 'true'), false)
})
