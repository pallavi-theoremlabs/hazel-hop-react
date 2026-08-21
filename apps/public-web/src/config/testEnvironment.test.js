import assert from 'node:assert/strict'
import test from 'node:test'

import { isTestEnvironmentEnabled } from './testEnvironment.js'

test('enables the handoff only for an explicit development or test environment', () => {
  assert.equal(isTestEnvironmentEnabled('development', 'true'), true)
  assert.equal(isTestEnvironmentEnabled('test', 'true'), true)
})

test('keeps production closed even when the dev flag is true', () => {
  assert.equal(isTestEnvironmentEnabled('production', 'true'), false)
})

test('keeps non-production environments closed when the dev flag is false', () => {
  assert.equal(isTestEnvironmentEnabled('development', 'false'), false)
  assert.equal(isTestEnvironmentEnabled('test', 'false'), false)
})

test('defaults closed for missing or unknown values', () => {
  assert.equal(isTestEnvironmentEnabled(undefined, undefined), false)
  assert.equal(isTestEnvironmentEnabled('staging', 'true'), false)
})
