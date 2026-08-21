import assert from 'node:assert/strict'
import test from 'node:test'
import { buildMemberPortalUrl } from './memberPortalUrl.js'

const MEMBER_PORTAL = 'https://member-portal-c4k9.onrender.com'

test('builds the member portal root URL', () => {
  assert.equal(
    buildMemberPortalUrl(MEMBER_PORTAL, '/'),
    'https://member-portal-c4k9.onrender.com/',
  )
})

test('builds a direct case handoff with the real institution context', () => {
  const result = buildMemberPortalUrl(MEMBER_PORTAL, '/case/case-123/nda', {
    institution_id: 'institution-456',
  })
  const url = new URL(result)

  assert.equal(url.pathname, '/case/case-123/nda')
  assert.equal(url.searchParams.get('institution_id'), 'institution-456')
})
