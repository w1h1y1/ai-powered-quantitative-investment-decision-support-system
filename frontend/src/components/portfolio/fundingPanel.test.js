import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function readSource(fileName) {
  return readFileSync(new URL(`./${fileName}`, import.meta.url), 'utf8')
}

test('FundingPanel uses the unified portfolio funding API', () => {
  const source = readSource('FundingPanel.jsx')

  assert.match(source, /portfolioApi\.funding\(\)/)
  assert.match(source, /portfolioApi\.createFunding/)
  assert.match(source, /flow_type/)
  assert.match(source, /transaction_date/)
  assert.match(source, /No funding history yet\./)
  assert.match(source, /\['DEPOSIT', 'Deposit'\]/)
  assert.match(source, /\['WITHDRAWAL', 'Withdrawal'\]/)
  assert.match(source, /setTimeout\(\(\) => setNotice\(''\), 3000\)/)
})

test('portfolioApi exposes funding endpoints through the shared API client', () => {
  const source = readSource('../../services/portfolioApi.js')

  assert.match(source, /apiRequest\('\/api\/portfolio\/funding\/'/)
})
