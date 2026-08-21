import assert from 'node:assert/strict'
import test from 'node:test'
import {
  integrationCasePath,
  integrationInstitutionId,
} from './integrationContext.js'

const CASE_ID = '11111111-1111-4111-8111-111111111111'
const INSTITUTION_ID = '22222222-2222-4222-8222-222222222222'

test('builds a direct real-case integration path', () => {
  assert.equal(
    integrationCasePath(CASE_ID, INSTITUTION_ID, 'nda'),
    `/case/${CASE_ID}/nda?institution_id=${INSTITUTION_ID}`,
  )
})

test('rejects malformed case and institution identifiers', () => {
  assert.equal(integrationCasePath('bad-case', INSTITUTION_ID), null)
  assert.equal(integrationCasePath(CASE_ID, 'bad-institution'), null)
  assert.equal(integrationInstitutionId('?institution_id=bad-institution'), '')
})

test('reads a valid institution from the handoff query', () => {
  assert.equal(
    integrationInstitutionId(`?institution_id=${INSTITUTION_ID}`),
    INSTITUTION_ID,
  )
})
