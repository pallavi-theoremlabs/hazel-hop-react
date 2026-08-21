import assert from 'node:assert/strict'
import test from 'node:test'
import { buildMemberPortalUrl } from './memberPortalUrl.js'

const MEMBER_PORTAL = 'https://member-portal-c4k9.onrender.com'

test('builds the production sign-in URL', () => {
  assert.equal(
    buildMemberPortalUrl(MEMBER_PORTAL, '/sign-in'),
    'https://member-portal-c4k9.onrender.com/sign-in',
  )
})

test('builds a create-account handoff with the real case context', () => {
  const result = buildMemberPortalUrl(MEMBER_PORTAL, '/create-account', {
    case_id: 'case-123',
    dev_institution_id: 'institution-456',
    next_path: '/case/case-123/nda',
  })
  const url = new URL(result)

  assert.equal(url.pathname, '/create-account')
  assert.equal(url.searchParams.get('case_id'), 'case-123')
  assert.equal(url.searchParams.get('dev_institution_id'), 'institution-456')
  assert.equal(url.searchParams.get('next_path'), '/case/case-123/nda')
})
