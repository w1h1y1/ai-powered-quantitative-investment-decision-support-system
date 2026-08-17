import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('./AIInsightsContent.jsx', import.meta.url),
  'utf8',
)

test('DeepSeek is only called from the explicit generate action', () => {
  const calls = source.split('agentAnalysisApi.analyze').length - 1
  assert.equal(calls, 1)
  const effectStart = source.indexOf('useEffect(() => {')
  const effectEnd = source.indexOf('}, [])')
  assert.doesNotMatch(source.slice(effectStart, effectEnd), /agentAnalysisApi\.analyze/)
})

test('loading state disables selector and button', () => {
  assert.match(source, /disabled=\{!selectedSymbol \|\| isLoading \|\| isSecuritiesLoading\}/)
  assert.match(source, /disabled=\{isSecuritiesLoading \|\| isLoading\}/)
})

test('stale responses are guarded by request id and symbol', () => {
  assert.match(source, /requestIdRef\.current !== requestId/)
  assert.match(source, /symbol !== selectedSymbol/)
})

test('frontend never contains DeepSeek secrets or direct provider access', () => {
  assert.doesNotMatch(source, /DEEPSEEK_API_KEY|sk-[A-Za-z0-9]{8,}|api\.deepseek\.com|Authorization/)
})

test('AI Insights does not render raw HTML', () => {
  assert.doesNotMatch(source, /dangerouslySetInnerHTML/)
})
