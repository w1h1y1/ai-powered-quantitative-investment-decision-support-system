import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function readDashboardSource() {
  return readFileSync(new URL('./DashboardContent.jsx', import.meta.url), 'utf8')
}

test('Dashboard loads its instrument list from the authenticated user holdings', () => {
  const source = readDashboardSource()

  assert.match(source, /holdingApi\.list\(\)/)
  assert.match(source, /normalizeHoldingsToDashboardSecurities\(response\)/)
})

test('Dashboard empty state still allows arbitrary security search', () => {
  const source = readDashboardSource()

  assert.match(source, /Search for a security\./)
  assert.match(source, /Select any supported symbol/)
  assert.match(source, /PopularSecurityChips/)
  assert.doesNotMatch(source, /Add active Security records in Django/)
  assert.doesNotMatch(source, /No portfolio holdings yet\./)
})
