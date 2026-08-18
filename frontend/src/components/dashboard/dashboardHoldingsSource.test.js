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

test('Dashboard empty state explains the user-facing portfolio workflow', () => {
  const source = readDashboardSource()

  assert.match(source, /No portfolio holdings yet\./)
  assert.match(source, /Add a position or search for a security to get started\./)
  assert.doesNotMatch(source, /Add active Security records in Django/)
})
