import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('./MarketAnalysisContent.jsx', import.meta.url),
  'utf8',
)

test('formal Market Analysis keeps Regime state separate from OHLCV state', () => {
  assert.match(source, /const \[marketData, setMarketData\] = useState\(null\)/)
  assert.match(source, /const \[marketRegimeRequest, setMarketRegimeRequest\] = useState\(\{/)

  const regimeEffectStart = source.indexOf('marketRegimeApi.get({ symbol: selectedSecuritySymbol })')
  const regimeEffectEnd = source.indexOf('}, [marketRegimeReloadKey, selectedSecurityId, selectedSecuritySymbol])')
  assert.ok(regimeEffectStart >= 0)
  assert.ok(regimeEffectEnd > regimeEffectStart)

  const regimeEffect = source.slice(regimeEffectStart, regimeEffectEnd)
  assert.match(regimeEffect, /\.catch\(\(error\) =>/)
  assert.match(regimeEffect, /data: null/)
  assert.match(regimeEffect, /status: 'error'/)
  assert.doesNotMatch(regimeEffect, /setMarketData\(|setMarketDataError\(/)
})

test('Regime panel is a sibling of the technical grid rather than a page-level error return', () => {
  const panelIndex = source.indexOf('<MarketRegimePanel')
  const gridIndex = source.indexOf('<div className="market-analysis-grid">')

  assert.ok(panelIndex >= 0)
  assert.ok(gridIndex > panelIndex)
  assert.doesNotMatch(source, /if \(marketRegimeError\)[\s\S]{0,120}return/)
  assert.doesNotMatch(source, /if \(visibleMarketRegimeRequest\.status === 'error'\)[\s\S]{0,120}return/)
})

test('technical ready branch does not depend on Market Regime request state', () => {
  const technicalBranchStart = source.indexOf('{selectedStock && !isMarketDataLoading && !marketDataError && hasChartData && (')
  const technicalBranch = source.slice(technicalBranchStart)

  assert.ok(technicalBranchStart >= 0)
  assert.doesNotMatch(technicalBranch, /marketRegimeRequest|visibleMarketRegimeRequest/)
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

test('security controls are rendered independently of Market Regime status', () => {
  const controlsIndex = source.indexOf('<MarketControls')
  const panelIndex = source.indexOf('<MarketRegimePanel')

  assert.ok(controlsIndex >= 0)
  assert.ok(panelIndex > controlsIndex)
  assert.match(source.slice(controlsIndex, panelIndex), /onStockChange=\{onSelectedSymbolChange\}/)
})
