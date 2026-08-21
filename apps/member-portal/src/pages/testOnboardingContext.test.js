import assert from 'node:assert/strict'
import test from 'node:test'

import { testOnboardingDestination } from './testOnboardingContext.js'

const CASE_ID = '11111111-1111-4111-8111-111111111111'
const INSTITUTION_ID = '22222222-2222-4222-8222-222222222222'

test('carries a valid real-case handoff to the existing NDA route', () => {
  const parameters = new URLSearchParams({
    case_id: CASE_ID,
    dev_institution_id: INSTITUTION_ID,
    next_path: `/case/${CASE_ID}/nda`,
  })

  assert.equal(
    testOnboardingDestination(`?${parameters}`),
    `/case/${CASE_ID}/nda?dev_institution_id=${INSTITUTION_ID}`,
  )
})

test('rejects invalid case or institution identifiers', () => {
  assert.equal(
    testOnboardingDestination(
      `?case_id=not-a-uuid&dev_institution_id=${INSTITUTION_ID}&next_path=/case/not-a-uuid/nda`,
    ),
    null,
  )
  assert.equal(
    testOnboardingDestination(
      `?case_id=${CASE_ID}&dev_institution_id=not-a-uuid&next_path=/case/${CASE_ID}/nda`,
    ),
    null,
  )
})

test('rejects a mismatched case or any broader member route', () => {
  assert.equal(
    testOnboardingDestination(
      `?case_id=${CASE_ID}&dev_institution_id=${INSTITUTION_ID}&next_path=/case/33333333-3333-4333-8333-333333333333/nda`,
    ),
    null,
  )
  assert.equal(
    testOnboardingDestination(
      `?case_id=${CASE_ID}&dev_institution_id=${INSTITUTION_ID}&next_path=/case/${CASE_ID}/documents`,
    ),
    null,
  )
})
