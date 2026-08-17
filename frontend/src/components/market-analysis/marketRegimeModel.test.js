import assert from 'node:assert/strict'
import test from 'node:test'
import { buildMarketRegimeRequestPath } from '../../services/marketRegimeApi.js'
import {
  formatMarketDate,
  formatPercent,
  formatRegimeLabel,
  getMarketRegimePanelState,
  isCurrentMarketRegimeRequest,
  marketRegimeResponseMatchesSecurity,
  normalizeMarketRegime,
} from './marketRegimeModel.js'

const securityIds = { AAPL: 1, JPM: 13, XOM: 14 }

function responseFor({
  available = true,
  confidence = 'medium',
  regime = 'sideways_range',
  sector = 'Information Technology',
  sectorBenchmark = 'XLK',
  symbol = 'AAPL',
} = {}) {
  return {
    symbol,
    security_id: securityIds[symbol] ?? 99,
    latest_market_date: '2026-08-13',
    historical_data_count: 320,
    required_core_history_count: 220,
    regime_available: available,
    regime_unavailable_reason: available ? null : 'insufficient_history',
    regime: available ? regime : null,
    confidence: available ? confidence : null,
    confidence_score: available ? 0.618 : null,
    trend: available
      ? { direction: 'bullish', score: 0.41, strength_score: 0.5, adx: 27.34 }
      : { direction: null, score: null, strength_score: null, adx: null },
    range: available
      ? { choppiness: 43.21, score: 0.35 }
      : { choppiness: null, score: null },
    momentum: available
      ? { score: 0.24, rsi: 56.71, macd_histogram: 1.2345, return_20d: 0.086742, return_60d: -0.031 }
      : { score: null, rsi: null, macd_histogram: null, return_20d: null, return_60d: null },
    volatility: available
      ? {
        atr_percent: 0.0234,
        realized_volatility_20d: 0.2851,
        volatility_percentile: 0.72,
        percentile_available: true,
        percentile_unavailable_reason: null,
      }
      : {
        atr_percent: null,
        realized_volatility_20d: null,
        volatility_percentile: null,
        percentile_available: false,
        percentile_unavailable_reason: 'insufficient_volatility_history',
      },
    relative_strength: available
      ? { score: 0.06, vs_spy_20d: 0.031, vs_spy_60d: -0.012, vs_sector_20d: 0.018, vs_sector_60d: 0.009 }
      : { score: null, vs_spy_20d: null, vs_spy_60d: null, vs_sector_20d: null, vs_sector_60d: null },
    sector,
    sector_source: 'security_metadata',
    sector_benchmark: sectorBenchmark,
    sector_context_available: available,
    sector_context_reason: available ? null : 'core_regime_unavailable',
    market_context: {
      broad_market: 'SPY',
      broad_market_context_available: available,
      broad_market_context_reason: available ? null : 'core_regime_unavailable',
      spy_regime: available ? 'sideways_range' : null,
      sector,
      sector_source: 'security_metadata',
      sector_benchmark: sectorBenchmark,
      sector_context_available: available,
      sector_context_reason: available ? null : 'core_regime_unavailable',
      sector_regime: available ? 'bullish_trend' : null,
      confirmation_score: available ? 0.67 : null,
    },
    market_data: {
      stock: {
        symbol,
        source: 'database_cache',
        record_count: 320,
        last_date: '2026-08-13',
        fetched_from_provider: false,
      },
      spy: null,
      sector: null,
    },
    explanation: available
      ? [
        'Price is above MA20, MA60 and MA200.',
        'ADX indicates a meaningful trend.',
        'Choppiness is trend-friendly.',
        'Current volatility is in approximately the 72nd percentile.',
        'RSI, MACD and trailing returns provide positive momentum confirmation.',
        'The stock is outperforming SPY over 20 trading days.',
      ]
      : ['Insufficient historical data to calculate the core market regime.'],
  }
}

test('market regime request path uses the normalized selected symbol', () => {
  assert.equal(buildMarketRegimeRequestPath(' jpm '), '/api/market-regime/?symbol=JPM')
})

test('normalizes every display module without converting missing values to zero', () => {
  const view = normalizeMarketRegime(responseFor(), 'AAPL', 1)

  assert.equal(view.symbol, 'AAPL')
  assert.equal(view.regimeLabel, 'Sideways / Range')
  assert.equal(view.regimeTone, 'neutral')
  assert.equal(view.confidence, 'Medium')
  assert.equal(view.trend.direction, 'Bullish')
  assert.equal(view.trend.strength, 'Meaningful')
  assert.equal(view.momentum.signal, 'Positive')
  assert.equal(view.range.condition, 'Trend-Friendly')
  assert.equal(view.marketContext.broadMarket, 'SPY')
  assert.equal(view.marketContext.sectorBenchmark, 'XLK')
  assert.equal(view.relativeStrength.vsSpy20d, 0.031)
  assert.equal(view.freshness.source, 'Cached market data')
  assert.equal(view.freshness.fetchedFromProvider, false)

  const unavailable = normalizeMarketRegime(responseFor({ available: false }), 'AAPL', 1)
  assert.equal(unavailable.available, false)
  assert.equal(unavailable.trend.adx, null)
  assert.equal(unavailable.momentum.return20d, null)
  assert.equal(unavailable.volatility.percentile, null)
  assert.match(unavailable.unavailableReason, /Insufficient historical data/)
})

test('maps all four backend regime enums to user-facing labels', () => {
  assert.equal(formatRegimeLabel('bullish_trend'), 'Bullish Trend')
  assert.equal(formatRegimeLabel('bearish_trend'), 'Bearish Trend')
  assert.equal(formatRegimeLabel('sideways_range'), 'Sideways / Range')
  assert.equal(formatRegimeLabel('high_volatility'), 'High Volatility')
})

test('uses backend trend direction instead of reducing a near-zero score to bearish', () => {
  const response = responseFor()
  response.trend = {
    ...response.trend,
    direction: 'mixed',
    score: -0.018106,
  }

  const view = normalizeMarketRegime(response, 'AAPL', 1)

  assert.equal(view.trend.direction, 'Mixed')
  assert.equal(view.trend.tone, 'neutral')
  assert.equal(view.trend.score, -0.018106)
})

test('supports bullish, bearish, mixed and neutral backend direction enums', () => {
  const expectations = [
    ['bullish', 'Bullish', 'positive'],
    ['bearish', 'Bearish', 'negative'],
    ['mixed', 'Mixed', 'neutral'],
    ['neutral', 'Neutral', 'neutral'],
  ]

  expectations.forEach(([rawDirection, label, tone]) => {
    const response = responseFor()
    response.trend.direction = rawDirection
    const view = normalizeMarketRegime(response, 'AAPL', 1)
    assert.equal(view.trend.direction, label)
    assert.equal(view.trend.tone, tone)
  })
})

test('missing trend direction displays N/A without falling back to score sign', () => {
  const response = responseFor()
  delete response.trend.direction
  response.trend.score = -0.9

  const view = normalizeMarketRegime(response, 'AAPL', 1)

  assert.equal(view.trend.direction, 'N/A')
  assert.equal(view.trend.tone, 'neutral')
})

test('AAPL, JPM and XOM use sector and benchmark values from each response', () => {
  const cases = [
    ['AAPL', 'Information Technology', 'XLK'],
    ['JPM', 'Financials', 'XLF'],
    ['XOM', 'Energy', 'XLE'],
  ]

  cases.forEach(([symbol, sector, benchmark]) => {
    const view = normalizeMarketRegime(
      responseFor({ symbol, sector, sectorBenchmark: benchmark }),
      symbol,
      securityIds[symbol],
    )
    assert.equal(view.marketContext.broadMarket, 'SPY')
    assert.equal(view.marketContext.sector, sector)
    assert.equal(view.marketContext.sectorBenchmark, benchmark)
  })
})

test('identity checks reject a response for a different symbol or security id', () => {
  const response = responseFor()
  assert.equal(marketRegimeResponseMatchesSecurity(response, 'AAPL', 1), true)
  assert.equal(marketRegimeResponseMatchesSecurity(response, 'JPM', 1), false)
  assert.equal(marketRegimeResponseMatchesSecurity(response, 'AAPL', 2), false)
  assert.throws(() => normalizeMarketRegime(response, 'JPM', 13), /did not match/)
})

test('switching symbols immediately hides the previous symbol result behind loading state', () => {
  const aapl = normalizeMarketRegime(responseFor(), 'AAPL', 1)
  const requestState = { symbol: 'AAPL', status: 'ready', data: aapl, error: '' }
  const panel = getMarketRegimePanelState(requestState, 'JPM')

  assert.equal(panel.symbol, 'JPM')
  assert.equal(panel.status, 'loading')
  assert.equal(panel.data, null)
  assert.equal(panel.error, '')
})

test('only the latest market-regime request is allowed to publish results', () => {
  assert.equal(isCurrentMarketRegimeRequest(3, 1), false)
  assert.equal(isCurrentMarketRegimeRequest(3, 2), false)
  assert.equal(isCurrentMarketRegimeRequest(3, 3), true)
})

test('formats API proportions and complete market dates without timezone drift', () => {
  assert.equal(formatPercent(0.086742, { signed: true }), '+8.67%')
  assert.equal(formatPercent(null), 'N/A')
  assert.equal(formatMarketDate('2026-08-13'), 'Aug 13, 2026')
})
