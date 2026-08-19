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
  assert.match(source, /disabled=\{!selectedSymbol \|\| isLoading \|\| isSecuritiesLoading \|\| isResolvingAsset\}/)
  assert.match(source, /disabled=\{isSecuritiesLoading \|\| isLoading \|\| isResolvingAsset\}/)
})

test('stale responses are guarded by request id and symbol', () => {
  assert.match(source, /requestIdRef\.current !== requestId/)
  assert.match(source, /symbol !== selectedSymbol/)
})

test('previous analysis is restored from the backend without calling DeepSeek', () => {
  const calls = source.split('agentAnalysisApi.latest').length - 1
  assert.equal(calls, 1)
  const latestIndex = source.indexOf('agentAnalysisApi.latest')
  const effectStart = source.lastIndexOf('useEffect(() => {', latestIndex)
  const effectEnd = source.indexOf('}, [selectedSymbol])', latestIndex)
  assert.ok(effectStart > -1 && effectEnd > -1)
  assert.doesNotMatch(source.slice(effectStart, effectEnd), /agentAnalysisApi\.analyze/)
})

test('regenerate keeps the previous analysis on failure and switches the button label', () => {
  assert.doesNotMatch(source, /const generateAnalysis[\s\S]{0,700}setAnalysis\(null\)/)
  assert.match(source, /isLoading \? 'Analyzing\.\.\.' : analysis \? 'Regenerate Analysis' : 'Generate AI Analysis'/)
  assert.match(source, /analysisUnavailable \? <UnavailableState reason=\{analysisUnavailable\} \/> : null/)
  assert.match(source, /error \? <ErrorState message=\{error\} \/> : null/)
})

test('history loading, no-history, and history API error are separate UI states', () => {
  assert.match(source, /isHistoryLoading/)
  assert.match(source, /historyError/)
  assert.match(source, /Loading previous analysis\.\.\./)
  assert.match(source, /Unable to load previous analysis\./)
})

test('stale history responses are guarded by request id and symbol', () => {
  assert.match(source, /historyRequestIdRef\.current !== requestId/)
  assert.match(source, /symbol !== selectedSymbol/)
})

test('frontend never contains DeepSeek secrets or direct provider access', () => {
  assert.doesNotMatch(source, /DEEPSEEK_API_KEY|sk-[A-Za-z0-9]{8,}|api\.deepseek\.com|Authorization/)
})

test('AI Insights does not render raw HTML', () => {
  assert.doesNotMatch(source, /dangerouslySetInnerHTML/)
})
