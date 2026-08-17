import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('./MarketAnalysisContent.jsx', import.meta.url),
  'utf8',
)

test('Market Analysis keeps Strategy Evaluation state separate from OHLCV and Regime state', () => {
  assert.match(source, /const \[strategyEvaluationRequest, setStrategyEvaluationRequest\] = useState\(\{/)
  assert.doesNotMatch(source, /const \[strategyEvaluationRequest, setStrategyEvaluationRequest\] = useState\(\{\s*data: marketData/)

  const effectStart = source.indexOf('strategyEvaluationApi.evaluate({ symbol: selectedSecuritySymbol })')
  const effectEnd = source.indexOf('}, [strategyEvaluationReloadKey, selectedSecurityId, selectedSecuritySymbol])')
  assert.ok(effectStart >= 0)
  assert.ok(effectEnd > effectStart)

  const effect = source.slice(effectStart, effectEnd)
  assert.match(effect, /\.catch\(\(error\) =>/)
  assert.match(effect, /data: null/)
  assert.match(effect, /status: 'error'/)
  assert.doesNotMatch(
    effect,
    /setMarketData\(|setMarketDataError\(|setMarketRegimeRequest\(/,
  )
})

test('Strategy Evaluation panel is a sibling of the technical grid rather than a page-level error return', () => {
  const regimePanelIndex = source.indexOf('<MarketRegimePanel')
  const strategyPanelIndex = source.indexOf('<StrategyEvaluationPanel')
  const gridIndex = source.indexOf('<div className="market-analysis-grid">')

  assert.ok(regimePanelIndex >= 0)
  assert.ok(strategyPanelIndex > regimePanelIndex)
  assert.ok(gridIndex > strategyPanelIndex)
  assert.doesNotMatch(source, /if \(strategyEvaluationError\)[\s\S]{0,120}return/)
  assert.doesNotMatch(source, /if \(visibleStrategyEvaluationRequest\.status === 'error'\)[\s\S]{0,120}return/)
})

test('technical ready branch does not depend on Strategy Evaluation request state', () => {
  const technicalBranchStart = source.indexOf('{selectedStock && !isMarketDataLoading && !marketDataError && hasChartData && (')
  const technicalBranch = source.slice(technicalBranchStart)

  assert.ok(technicalBranchStart >= 0)
  assert.doesNotMatch(technicalBranch, /strategyEvaluationRequest|visibleStrategyEvaluationRequest/)
  for (const component of [
    'MarketPriceChart',
    'IndicatorOverlayControls',
    'RsiChart',
    'TechnicalSummary',
    'VolumeChart',
    'MacdChart',
  ]) {
    assert.match(technicalBranch, new RegExp(`<${component}`))
  }
})

test('switching symbols resets the Strategy Evaluation request state before reloading', () => {
  const effectStart = source.indexOf('strategyEvaluationApi.evaluate({ symbol: selectedSecuritySymbol })')
  const effectPrefix = source.slice(0, effectStart)

  assert.match(effectPrefix, /setStrategyEvaluationRequest\(\{/)
  assert.match(effectPrefix, /status: 'loading'/)
  assert.match(effectPrefix, /symbol: selectedSecuritySymbol/)
})

test('Strategy Evaluation retry re-enters loading state without touching other modules', () => {
  const retryStart = source.indexOf('const retryStrategyEvaluation')
  assert.ok(retryStart >= 0)
  const retry = source.slice(retryStart, retryStart + 420)
  assert.match(retry, /setStrategyEvaluationRequest\(/)
  assert.match(retry, /status: 'loading'/)
  assert.match(retry, /setStrategyEvaluationReloadKey\(/)
  assert.doesNotMatch(retry, /setMarketData|setMarketRegimeRequest/)
})
