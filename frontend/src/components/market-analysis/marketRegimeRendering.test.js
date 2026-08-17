import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

let vite
let MarketRegimePanel
let normalizeMarketRegime
let getMarketRegimePanelState

before(async () => {
  vite = await createServer({ appType: 'custom', server: { hmr: false, middlewareMode: true } })
  ;({ default: MarketRegimePanel } = await vite.ssrLoadModule(
    '/src/components/market-analysis/MarketRegimePanel.jsx',
  ))
  ;({ normalizeMarketRegime, getMarketRegimePanelState } = await vite.ssrLoadModule(
    '/src/components/market-analysis/marketRegimeModel.js',
  ))
})

after(async () => {
  await vite?.close()
})

function rawResponse({
  available = true,
  regime = 'high_volatility',
  sector = 'Information Technology',
  sectorBenchmark = 'XLK',
  securityId = 1,
  symbol = 'AAPL',
} = {}) {
  return {
    symbol,
    security_id: securityId,
    latest_market_date: '2026-08-13',
    regime_available: available,
    regime_unavailable_reason: available ? null : 'insufficient_history',
    regime: available ? regime : null,
    confidence: available ? 'medium' : null,
    confidence_score: available ? 0.61 : null,
    trend: {
      direction: available ? 'bullish' : null,
      score: available ? 0.42 : null,
      adx: available ? 28.2 : null,
    },
    range: { choppiness: available ? 42.5 : null, score: available ? 0.32 : null },
    momentum: {
      score: available ? 0.31 : null,
      rsi: available ? 58.4 : null,
      macd_histogram: available ? 1.2345 : null,
      return_20d: available ? 0.086742 : null,
      return_60d: available ? -0.0123 : null,
    },
    volatility: {
      atr_percent: available ? 0.024 : null,
      realized_volatility_20d: available ? 0.31 : null,
      volatility_percentile: available ? 0.9 : null,
      percentile_available: available,
      percentile_unavailable_reason: available ? null : 'insufficient_volatility_history',
    },
    relative_strength: {
      score: available ? 0.04 : null,
      vs_spy_20d: available ? 0.031 : null,
      vs_spy_60d: available ? -0.01 : null,
      vs_sector_20d: available ? 0.018 : null,
      vs_sector_60d: available ? 0.008 : null,
    },
    sector,
    sector_benchmark: sectorBenchmark,
    market_context: {
      broad_market: 'SPY',
      broad_market_context_available: available,
      broad_market_context_reason: available ? null : 'core_regime_unavailable',
      spy_regime: available ? 'sideways_range' : null,
      sector,
      sector_benchmark: sectorBenchmark,
      sector_context_available: available,
      sector_context_reason: available ? null : 'core_regime_unavailable',
      sector_regime: available ? 'bullish_trend' : null,
      confirmation_score: available ? 0.64 : null,
    },
    market_data: {
      stock: { source: 'database_cache', last_date: '2026-08-13', fetched_from_provider: false },
    },
    explanation: available
      ? [
        'Price is above MA20, MA60 and MA200.',
        'ADX indicates a meaningful trend.',
        'Choppiness is trend-friendly.',
        'Current volatility is in approximately the 90th percentile.',
        'RSI, MACD and trailing returns provide positive momentum confirmation.',
        'The stock is outperforming SPY over 20 trading days.',
      ]
      : ['Insufficient historical data to calculate the core market regime.'],
  }
}

function renderPanel(props) {
  const html = renderToStaticMarkup(React.createElement(MarketRegimePanel, props))
  return {
    html,
    text: html.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim(),
  }
}

test('available regime renders every required Market Analysis module', () => {
  const regime = normalizeMarketRegime(rawResponse(), 'AAPL', 1)
  const { text } = renderPanel({ symbol: 'AAPL', regime, isLoading: false, error: '' })

  assert.match(text, /Market Regime AAPL High Volatility Confidence: Medium/)
  assert.match(text, /Trend Direction Bullish Strength Meaningful ADX 28\.20/)
  assert.match(text, /Momentum Signal Positive RSI 58\.40 MACD Histogram 1\.2345/)
  assert.match(text, /20D Return \+8\.67%/)
  assert.match(text, /Volatility ATR % 2\.40% Realized Volatility \(20D\) 31\.00% Historical Percentile 90th percentile/)
  assert.match(text, /Range Condition Trend-Friendly Choppiness Index 42\.50/)
  assert.match(text, /Market Context Broad Market \(SPY\) Sideways \/ Range/)
  assert.match(text, /Information Technology \(XLK\) Bullish Trend/)
  assert.match(text, /Relative Strength vs SPY \(20D\) \+3\.10%/)
  assert.match(text, /Why This Regime/)
  assert.match(text, /Data through Aug 13, 2026 Cached market data Reused cached data/)
})

test('all four backend regimes render their user-facing label and tone', () => {
  const cases = [
    ['bullish_trend', 'Bullish Trend', 'regime-positive'],
    ['bearish_trend', 'Bearish Trend', 'regime-negative'],
    ['sideways_range', 'Sideways / Range', 'regime-neutral'],
    ['high_volatility', 'High Volatility', 'regime-warning'],
  ]

  cases.forEach(([rawRegime, label, tone]) => {
    const regime = normalizeMarketRegime(rawResponse({ regime: rawRegime }), 'AAPL', 1)
    const { html, text } = renderPanel({ symbol: 'AAPL', regime, isLoading: false, error: '' })
    assert.match(text, new RegExp(label.replace('/', '\\/')))
    assert.match(html, new RegExp(tone))
  })
})

test('AAPL-like mixed structure renders Direction Mixed despite a slightly negative score', () => {
  const response = rawResponse()
  response.trend.direction = 'mixed'
  response.trend.score = -0.018106
  response.trend.adx = 22.566829
  response.explanation = [
    'Moving-average direction is mixed.',
    'MA20 and MA60 slopes do not agree.',
    'ADX indicates a forming trend.',
  ]
  const regime = normalizeMarketRegime(response, 'AAPL', 1)
  const { html, text } = renderPanel({ symbol: 'AAPL', regime, isLoading: false, error: '' })

  assert.match(text, /Trend Direction Mixed Strength Forming ADX 22\.57/)
  assert.match(text, /Moving-average direction is mixed\./)
  assert.match(html, /is-neutral[^>]*>Mixed/)
  assert.doesNotMatch(text, /Direction Bearish/)
})

test('AAPL, JPM and XOM render the sector benchmark supplied by the API', () => {
  const cases = [
    ['AAPL', 1, 'Information Technology', 'XLK'],
    ['JPM', 13, 'Financials', 'XLF'],
    ['XOM', 14, 'Energy', 'XLE'],
  ]

  cases.forEach(([symbol, securityId, sector, benchmark]) => {
    const regime = normalizeMarketRegime(
      rawResponse({ symbol, securityId, sector, sectorBenchmark: benchmark }),
      symbol,
      securityId,
    )
    const { text } = renderPanel({ symbol, regime, isLoading: false, error: '' })
    assert.match(text, new RegExp(`${symbol}.*${sector} \\(${benchmark}\\)`))
  })
})

test('loading a new stock never renders the previous stock result', () => {
  const oldRegime = normalizeMarketRegime(rawResponse(), 'AAPL', 1)
  const { text } = renderPanel({
    symbol: 'JPM',
    regime: oldRegime,
    isLoading: true,
    error: '',
  })
  assert.match(text, /Loading market regime for JPM/)
  assert.doesNotMatch(text, /AAPL|High Volatility|ADX 28\.20/)
})

test('HTTP error and 200 unavailable states remain explicit and distinct', () => {
  const errors = [
    'Internal market regime failure.',
    'Market data provider rate limit reached.',
    'Unable to connect to the server. Please try again later.',
  ]

  errors.forEach((error) => {
    const errorState = renderPanel({
      symbol: 'XOM',
      regime: null,
      isLoading: false,
      error,
      onRetry: () => {},
    })
    assert.match(errorState.html, /role="alert"/)
    assert.match(errorState.text, /Market regime temporarily unavailable/)
    assert.match(errorState.text, new RegExp(error.replaceAll('.', '\\.')))
    assert.match(errorState.text, /Retry/)
    assert.doesNotMatch(errorState.text, /Confidence:|Direction:|Sideways \/ Range|Trend: Neutral|NaN|undefined/)
  })

  const unavailable = normalizeMarketRegime(rawResponse({ available: false }), 'AAPL', 1)
  const unavailableState = renderPanel({
    symbol: 'AAPL',
    regime: unavailable,
    isLoading: false,
    error: '',
  })
  assert.match(unavailableState.text, /Market regime unavailable for AAPL/)
  assert.match(unavailableState.text, /Insufficient historical data/)
  assert.match(unavailableState.text, /N\/A/)
  assert.doesNotMatch(unavailableState.text, /temporarily unavailable|Retry/)
})

test('AAPL error is cleared while JPM loads and JPM success renders normally', () => {
  const aaplError = {
    symbol: 'AAPL',
    status: 'error',
    data: null,
    error: 'Internal market regime failure.',
  }
  const errorView = getMarketRegimePanelState(aaplError, 'AAPL')
  const errorPanel = renderPanel({
    symbol: 'AAPL',
    regime: errorView.data,
    isLoading: false,
    error: errorView.error,
  })
  assert.match(errorPanel.text, /temporarily unavailable/)

  const loadingView = getMarketRegimePanelState(aaplError, 'JPM')
  const loadingPanel = renderPanel({
    symbol: 'JPM',
    regime: loadingView.data,
    isLoading: loadingView.status === 'loading',
    error: loadingView.error,
  })
  assert.match(loadingPanel.text, /Loading market regime for JPM/)
  assert.doesNotMatch(loadingPanel.text, /AAPL|Internal market regime failure/)

  const jpmRegime = normalizeMarketRegime(rawResponse({
    regime: 'sideways_range',
    sector: 'Financials',
    sectorBenchmark: 'XLF',
    securityId: 13,
    symbol: 'JPM',
  }), 'JPM', 13)
  const successView = getMarketRegimePanelState({
    symbol: 'JPM',
    status: 'ready',
    data: jpmRegime,
    error: '',
  }, 'JPM')
  const successPanel = renderPanel({
    symbol: 'JPM',
    regime: successView.data,
    isLoading: false,
    error: successView.error,
  })
  assert.match(successPanel.text, /JPM Sideways \/ Range/)
  assert.match(successPanel.text, /Financials \(XLF\)/)
  assert.doesNotMatch(successPanel.text, /Internal market regime failure|temporarily unavailable/)
})

test('AAPL success is cleared before a later JPM error is shown', () => {
  const aaplRegime = normalizeMarketRegime(rawResponse(), 'AAPL', 1)
  const aaplReady = {
    symbol: 'AAPL',
    status: 'ready',
    data: aaplRegime,
    error: '',
  }

  const loadingView = getMarketRegimePanelState(aaplReady, 'JPM')
  const loadingPanel = renderPanel({
    symbol: 'JPM',
    regime: loadingView.data,
    isLoading: loadingView.status === 'loading',
    error: loadingView.error,
  })
  assert.match(loadingPanel.text, /Loading market regime for JPM/)
  assert.doesNotMatch(loadingPanel.text, /AAPL|High Volatility|Information Technology|XLK/)

  const jpmError = getMarketRegimePanelState({
    symbol: 'JPM',
    status: 'error',
    data: null,
    error: 'Internal market regime failure.',
  }, 'JPM')
  const errorPanel = renderPanel({
    symbol: 'JPM',
    regime: jpmError.data,
    isLoading: false,
    error: jpmError.error,
  })
  assert.match(errorPanel.text, /Market regime temporarily unavailable/)
  assert.match(errorPanel.text, /Internal market regime failure/)
  assert.doesNotMatch(errorPanel.text, /AAPL|High Volatility|Information Technology|XLK/)
})
