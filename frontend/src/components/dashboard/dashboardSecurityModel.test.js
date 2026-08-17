import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildDashboardPriceChart,
  buildDashboardIndicators,
  buildDashboardTechnicalIndicators,
  buildMarketDataRequestParams,
  clampDashboardVisibleWindow,
  createDefaultCustomMarketDataRange,
  dashboardMarketDataRanges,
  estimateMarketDataPoints,
  filterSecurityOptions,
  formatDashboardCandleTooltip,
  formatDashboardDateLabel,
  getActiveSecurities,
  getDefaultMarketDataInterval,
  getMarketDataDebugSummary,
  getMarketSummaryDebugSummary,
  marketDataResponseMatchesRequest,
  normalizeMarketData,
  normalizeDashboardVisibleWindow,
  normalizeMarketSummary,
  panDashboardVisibleWindow,
  readStoredSecurityId,
  resolveSelectedSecurityId,
  shouldApplyMarketDataResponse,
  upsertDashboardSecurity,
  validateCustomMarketDataRange,
  zoomDashboardVisibleWindow,
  writeStoredSecurityId,
} from './dashboardSecurityModel.js'

function security(overrides = {}) {
  return {
    id: 1,
    symbol: 'AAPL',
    name: 'Apple Inc.',
    asset_type: 'STOCK',
    exchange: 'NASDAQ',
    currency: 'USD',
    is_active: true,
    ...overrides,
  }
}

function storageMock(initialValue = '') {
  const values = new Map(initialValue ? [['aiquantification.dashboard.selectedSecurityId', initialValue]] : [])
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  }
}

test('normalizes API securities and keeps only active records', () => {
  const securities = getActiveSecurities([
    security({ id: 7, symbol: ' msft ', name: ' Microsoft ', is_active: true }),
    security({ id: 8, symbol: 'QQQ', is_active: false }),
    null,
  ])

  assert.deepEqual(securities, [{
    id: 7,
    symbol: 'MSFT',
    name: 'Microsoft',
    assetType: 'STOCK',
    exchange: 'NASDAQ',
    currency: 'USD',
    micCode: '',
    country: '',
    isActive: true,
  }])
})

test('adds a remotely resolved Security once and keeps the universe sorted', () => {
  const current = getActiveSecurities([
    security({ id: 1, symbol: 'AAPL', name: 'Apple Inc.' }),
    security({ id: 2, symbol: 'MSFT', name: 'Microsoft Corporation' }),
  ])
  const jpm = getActiveSecurities([
    security({
      id: 13,
      symbol: 'JPM',
      name: 'JPMorgan Chase & Co.',
      exchange: 'NYSE',
      mic_code: 'XNYS',
    }),
  ])[0]

  const added = upsertDashboardSecurity(current, jpm)
  const reused = upsertDashboardSecurity(added, { ...jpm, name: 'JPMorgan Chase & Co.' })

  assert.deepEqual(added.map((item) => item.symbol), ['AAPL', 'JPM', 'MSFT'])
  assert.equal(reused.filter((item) => item.id === 13).length, 1)
})

test('filters securities by symbol or company name', () => {
  const securities = getActiveSecurities([
    security({ id: 1, symbol: 'AAPL', name: 'Apple Inc.' }),
    security({ id: 2, symbol: 'MSFT', name: 'Microsoft Corporation' }),
  ])

  assert.equal(filterSecurityOptions(securities, 'ms').at(0).symbol, 'MSFT')
  assert.equal(filterSecurityOptions(securities, 'apple').at(0).symbol, 'AAPL')
})

test('resolves selection using current id, stored id, then first active security', () => {
  const securities = getActiveSecurities([
    security({ id: 1, symbol: 'AAPL' }),
    security({ id: 2, symbol: 'MSFT' }),
  ])

  assert.equal(resolveSelectedSecurityId({ securities, currentSecurityId: 2, storedSecurityId: 1 }), '2')
  assert.equal(resolveSelectedSecurityId({ securities, currentSecurityId: 99, storedSecurityId: 1 }), '1')
  assert.equal(resolveSelectedSecurityId({ securities, currentSecurityId: 99, storedSecurityId: 88 }), '1')
  assert.equal(resolveSelectedSecurityId({ securities: [], currentSecurityId: 1, storedSecurityId: 1 }), '')
})

test('stores the selected security id without depending on array index', () => {
  const storage = storageMock()

  writeStoredSecurityId(42, storage)
  assert.equal(readStoredSecurityId(storage), '42')
  writeStoredSecurityId('', storage)
  assert.equal(readStoredSecurityId(storage), '')
})

test('normalizes market summary API response into card values and real sparkline data', () => {
  const summary = normalizeMarketSummary({
    source: 'TWELVE_DATA',
    status: 'ok',
    cache_status: 'fresh',
    generated_at: '2026-07-30T12:00:00+00:00',
    updated_at: '2026-07-29',
    metadata: {
      count: 2,
      symbols: ['BTC/USD', 'SPY'],
      cache_status: 'fresh',
    },
    items: [
      {
        key: 'bitcoin',
        symbol: 'BTC/USD',
        display_name: 'Bitcoin',
        latest_price: 117432.1234,
        previous_close: 118651.3734,
        absolute_change: -1219.25,
        percentage_change: -1.02761,
        updated_at: '2026-07-29',
        sparkline: [
          { datetime: '2026-07-28', close: 118651.3734 },
          { datetime: '2026-07-29', close: 117432.1234 },
        ],
        data_status: 'ok',
        error: '',
      },
      {
        key: 'sp500',
        symbol: 'SPY',
        display_name: 'S&P 500 ETF proxy',
        provider_symbol: 'SPY',
        requested_symbol: 'SPX',
        latest_price: 645.79,
        previous_close: 644.54,
        absolute_change: 12.5,
        percentage_change: 1.9394,
        updated_at: '2026-07-29',
        sparkline: [
          { datetime: '2026-07-28', close: 644.54 },
          { datetime: '2026-07-29', close: 645.79 },
        ],
        data_status: 'ok',
        error: '',
      },
    ],
  })

  assert.equal(summary.statusLabel, 'Latest Market Data')
  assert.equal(summary.lastUpdatedLabel, 'Last updated: Jul 29, 2026')
  assert.equal(summary.items[0].symbol, 'SPY')
  assert.equal(summary.items[0].name, 'S&P 500 ETF proxy')
  assert.equal(summary.items[0].providerSymbol, 'SPY')
  assert.equal(summary.items[0].value, '645.79')
  assert.equal(summary.items[0].change, '+12.50')
  assert.equal(summary.items[0].percent, '+1.94%')
  assert.equal(summary.items[0].latestPrice, 645.79)
  assert.equal(summary.items[0].absoluteChange, 12.5)
  assert.equal(summary.items[0].percentageChange, 1.9394)
  assert.deepEqual(summary.items[0].sparkline.map((point) => point.close), [644.54, 645.79])
  assert.equal(summary.items[0].sparkline.at(-1).close, summary.items[0].latestPrice)
  assert.equal(summary.items[3].symbol, 'BTC/USD')
  assert.equal(summary.items[3].value, '$117,432.12')
  assert.equal(summary.items[3].change, '-$1,219.25')
  assert.equal(summary.items[3].direction, 'down')
  assert.equal(summary.cacheStatus, 'fresh')
})

test('keeps unavailable market summary cards without falling back to demo prices', () => {
  const summary = normalizeMarketSummary({
    source: 'TWELVE_DATA',
    status: 'partial',
    updated_at: '2026-07-29',
    items: [
      {
        symbol: 'DIA',
        display_name: 'Dow Jones Industrial Average ETF proxy',
        latest_price: null,
        previous_close: null,
        absolute_change: null,
        percentage_change: null,
        updated_at: '',
        sparkline: [],
        data_status: 'unavailable',
        error: 'Market data unavailable.',
      },
    ],
  })

  const dowJonesCard = summary.items.find((item) => item.symbol === 'DIA')
  assert.equal(dowJonesCard.value, 'Unavailable')
  assert.equal(dowJonesCard.change, 'Unavailable')
  assert.equal(dowJonesCard.percent, 'N/A')
  assert.deepEqual(dowJonesCard.sparkline, [])
  assert.equal(dowJonesCard.error, 'Market data unavailable.')
  assert.equal(dowJonesCard.dataStatus, 'unavailable')
})

test('summarizes market summary rendering for response-to-card verification', () => {
  const response = {
    source: 'TWELVE_DATA',
    status: 'ok',
    cache_status: 'fresh',
    generated_at: '2026-07-30T12:00:00+00:00',
    updated_at: '2026-07-29',
    metadata: {
      count: 1,
      symbols: ['SPY'],
    },
    items: [
      {
        key: 'sp500',
        symbol: 'SPY',
        display_name: 'S&P 500 ETF proxy',
        provider_symbol: 'SPY',
        latest_price: 645.79,
        previous_close: 644.54,
        absolute_change: 12.5,
        percentage_change: 1.9394,
        updated_at: '2026-07-29',
        sparkline: [
          { datetime: '2026-07-28', close: 644.54 },
          { datetime: '2026-07-29', close: 645.79 },
        ],
        data_status: 'ok',
        error: '',
      },
    ],
  }
  const summary = normalizeMarketSummary(response)
  const debugSummary = getMarketSummaryDebugSummary(response, summary)

  assert.equal(debugSummary.renderedItems[0].symbol, 'SPY')
  assert.equal(debugSummary.renderedItems[0].providerSymbol, 'SPY')
  assert.equal(debugSummary.renderedItems[0].latestPrice, 645.79)
  assert.equal(debugSummary.renderedItems[0].absoluteChange, 12.5)
  assert.equal(debugSummary.renderedItems[0].percentageChange, 1.9394)
  assert.equal(debugSummary.renderedItems[0].sparklineLastClose, 645.79)
  assert.equal(debugSummary.cacheStatus, 'fresh')
})

test('normalizes backend OHLCV response for candlestick rendering', () => {
  const marketData = normalizeMarketData({
    range: '3M',
    interval: '1day',
    source: 'TWELVE_DATA',
    is_stale: false,
    values: [
      { date: '2026-07-23', open: '100.00', high: '105.00', low: '99.50', close: '104.00', volume: 123456 },
      { date: '2026-07-24', open: '104.00', high: '108.00', low: '103.00', close: '107.50', volume: '234567' },
    ],
    warmup_values: [
      { date: '2026-07-22', open: '98.00', high: '101.00', low: '97.50', close: '100.00', volume: '111111' },
    ],
  })

  assert.equal(marketData.range, '3M')
  assert.equal(marketData.interval, '1day')
  assert.equal(marketData.source, 'TWELVE_DATA')
  assert.equal(marketData.candles.length, 2)
  assert.equal(marketData.candles[1].close, 107.5)
  assert.equal(marketData.candles[1].volume, 234567)
  assert.strictEqual(marketData.visibleData, marketData.candles)
  assert.equal(marketData.visibleData.length, 2)
  assert.equal(marketData.fullData.length, 3)
  assert.equal(marketData.fullData.at(-1).close, 107.5)
  assert.equal(marketData.warmupCandles.length, 1)
  assert.equal(marketData.warmupCandles[0].date, '2026-07-22')
})

test('normalizes OHLCV values into one ascending deduplicated chart source', () => {
  const marketData = normalizeMarketData({
    security: security({ id: 1, symbol: 'AAPL' }),
    range: '1D',
    interval: '1min',
    source: 'TWELVE_DATA',
    values: [
      { date: '2026-07-29 15:59:00', open: '337.900000', high: '338.500000', low: '337.800000', close: '338.070007', volume: '1500' },
      { date: '2026-07-29 15:58:00', open: '337.100000', high: '337.900000', low: '337.000000', close: '337.500000', volume: '1300' },
      { date: '2026-07-29 15:58:00', open: '337.200000', high: '338.000000', low: '337.100000', close: '337.600000', volume: '1400' },
    ],
    warmup_values: [
      { date: '2026-07-28 15:59:00', open: '332.000000', high: '333.000000', low: '331.500000', close: '332.750000', volume: '900' },
    ],
  })

  assert.deepEqual(marketData.candles.map((candle) => candle.date), [
    '2026-07-29 15:58:00',
    '2026-07-29 15:59:00',
  ])
  assert.equal(marketData.candles[0].close, 337.6)
  assert.equal(marketData.candles.at(-1).close, 338.070007)
  assert.equal(marketData.candles.at(-1).volume, 1500)
  assert.strictEqual(marketData.visibleData, marketData.candles)
  assert.equal(marketData.normalizedLastRecord.close, 338.070007)
  assert.deepEqual(marketData.fullData.map((candle) => candle.date), [
    '2026-07-28 15:59:00',
    '2026-07-29 15:58:00',
    '2026-07-29 15:59:00',
  ])
  assert.equal(marketData.fullData.at(-1).close, 338.070007)
  assert.equal(marketData.warmupCandles.length, 1)
  assert.equal(marketData.warmupCandles[0].close, 332.75)
  assert.equal(marketData.metadata.lastDatetime, '2026-07-29 15:59:00')
})

test('accepts only market data responses matching the active security range and interval', () => {
  const request = { securityId: 1, range: '1D', interval: '1min' }
  const matchingResponse = {
    security: security({ id: 1, symbol: 'AAPL' }),
    range: '1D',
    interval: '1min',
  }

  assert.equal(marketDataResponseMatchesRequest(matchingResponse, request), true)
  assert.equal(marketDataResponseMatchesRequest({ ...matchingResponse, security: security({ id: 2 }) }, request), false)
  assert.equal(marketDataResponseMatchesRequest({ ...matchingResponse, range: '1M' }, request), false)
  assert.equal(marketDataResponseMatchesRequest({ ...matchingResponse, interval: '1day' }, request), false)
  assert.equal(marketDataResponseMatchesRequest({
    metadata: { security_id: 1, requested_range: 'CUSTOM', interval: '1day' },
  }, { securityId: 1, range: 'Custom', interval: '1day' }), true)
})

test('builds dashboard chart from selected Security plus real backend OHLCV', () => {
  const selectedSecurity = getActiveSecurities([
    security({ id: 2, symbol: 'MSFT', name: 'Microsoft Corporation' }),
  ])[0]
  const marketData = normalizeMarketData({
    range: '3M',
    interval: '1day',
    source: 'TWELVE_DATA',
    is_stale: false,
    values: [
      { date: '2026-07-23', open: '100.00', high: '105.00', low: '99.50', close: '104.00', volume: 123456 },
      { date: '2026-07-24', open: '104.00', high: '108.00', low: '103.00', close: '107.50', volume: 234567 },
    ],
  })

  const chart = buildDashboardPriceChart({
    security: selectedSecurity,
    marketData,
    range: '3M',
  })

  assert.deepEqual(chart.ranges, dashboardMarketDataRanges)
  assert.deepEqual(chart.ranges, ['1D', '1W', '1M', '3M', '6M', '1Y', '5Y', 'Custom'])
  assert.equal(chart.symbol, 'MSFT')
  assert.equal(chart.currency, 'USD')
  assert.equal(chart.interval, '1day')
  assert.equal(chart.intervalLabel, 'daily OHLCV')
  assert.equal(chart.intervalOptions.length, 9)
  assert.equal(chart.price, '$107.50')
  assert.equal(chart.change, '+$3.50')
  assert.equal(chart.percent, '+3.37%')
  assert.equal(chart.candles.length, 2)
  assert.match(chart.dataSourceNote, /Twelve Data daily OHLCV/)
})

test('builds all chart modes from the same normalized OHLCV response', () => {
  const selectedSecurity = getActiveSecurities([
    security({ id: 1, symbol: 'AAPL', name: 'Apple Inc.' }),
  ])[0]
  const marketData = normalizeMarketData({
    security: security({ id: 1, symbol: 'AAPL' }),
    range: '1D',
    interval: '1min',
    source: 'TWELVE_DATA',
    values: [
      { date: '2026-07-29 15:58:00', open: '337.100000', high: '338.000000', low: '337.000000', close: '337.600000', volume: '1400' },
      { date: '2026-07-29 15:59:00', open: '337.900000', high: '338.500000', low: '337.800000', close: '338.070007', volume: '1500' },
    ],
  })

  const chart = buildDashboardPriceChart({
    security: selectedSecurity,
    marketData,
    range: '1D',
    requestedInterval: '1min',
  })

  assert.strictEqual(chart.candles, marketData.visibleData)
  assert.equal(chart.candles.at(-1).close, 338.070007)
  assert.equal(chart.price, '$338.07')
  assert.equal(chart.debug.topPriceValue, 338.070007)
  assert.equal(chart.debug.topPriceSource, 'visibleData[visibleData.length - 1].close')
  assert.equal(chart.indicators.length, chart.candles.length)
  assert.match(chart.dataSourceNote, /last returned OHLCV close/)
})

test('uses visible OHLCV last close for chart and top price instead of warm-up data', () => {
  const selectedSecurity = getActiveSecurities([
    security({ id: 1, symbol: 'AAPL', name: 'Apple Inc.' }),
  ])[0]
  const marketData = normalizeMarketData({
    security: security({ id: 1, symbol: 'AAPL' }),
    range: '1D',
    interval: '1min',
    source: 'TWELVE_DATA',
    warmup_values: [
      { date: '2026-07-29 14:58:00', open: '333.00', high: '334.00', low: '332.90', close: '333.85', volume: '1200' },
    ],
    values: [
      { date: '2026-07-29 15:58:00', open: '337.100000', high: '338.000000', low: '337.000000', close: '337.600000', volume: '1400' },
      { date: '2026-07-29 15:59:00', open: '337.900000', high: '338.500000', low: '337.800000', close: '338.070007', volume: '1500' },
    ],
  })

  const chart = buildDashboardPriceChart({
    security: selectedSecurity,
    marketData,
    range: '1D',
    requestedInterval: '1min',
  })

  assert.equal(marketData.warmupCandles.at(-1).close, 333.85)
  assert.equal(marketData.visibleData.at(-1).close, 338.070007)
  assert.equal(chart.candles.at(-1).close, 338.070007)
  assert.equal(chart.debug.finalChartDataLastRecord.close, 338.070007)
  assert.equal(chart.debug.topPriceValue, 338.070007)
  assert.equal(chart.price, '$338.07')
})

test('ignores invalid latest OHLCV rows when selecting the top price', () => {
  const selectedSecurity = getActiveSecurities([
    security({ id: 1, symbol: 'AAPL', name: 'Apple Inc.' }),
  ])[0]
  const marketData = normalizeMarketData({
    security: security({ id: 1, symbol: 'AAPL' }),
    range: '1D',
    interval: '1min',
    source: 'TWELVE_DATA',
    warmup_values: [
      { date: '2026-07-28 15:59:00', open: '333.00', high: '334.00', low: '332.50', close: '333.430000', volume: '1800' },
    ],
    values: [
      { date: '2026-07-29 16:00:00', open: '338.00', high: '339.00', low: '337.50', close: '339.000000', volume: '1600' },
      { date: '2026-07-29 15:58:00', open: '337.100000', high: '338.000000', low: '337.000000', close: '337.600000', volume: '1400' },
      { date: '2026-07-29 15:59:00', open: '337.900000', high: '338.500000', low: '337.800000', close: '338.070000', volume: '1500' },
      { date: '2026-07-29 16:01:00', open: '338.00', high: '338.50', low: '337.50', close: 'bad-close', volume: '1700' },
    ],
  })

  const chart = buildDashboardPriceChart({
    security: selectedSecurity,
    marketData,
    range: '1D',
    requestedInterval: '1min',
  })

  assert.deepEqual(marketData.candles.map((candle) => candle.date), [
    '2026-07-29 15:58:00',
    '2026-07-29 15:59:00',
  ])
  assert.equal(chart.price, '$338.07')
  assert.equal(chart.change, '+$4.64')
  assert.equal(chart.percent, '+1.39%')
})

test('calculates AAPL latest price and daily change from the same official session OHLCV data', () => {
  const selectedSecurity = getActiveSecurities([
    security({ id: 1, symbol: 'AAPL', name: 'Apple Inc.' }),
  ])[0]
  const marketData = normalizeMarketData({
    security: security({ id: 1, symbol: 'AAPL' }),
    range: '1D',
    interval: '1min',
    source: 'TWELVE_DATA',
    metadata: {
      session_close_adjustments: [
        {
          date: '2026-07-30',
          timestamp: '2026-07-30 15:59:00',
          original_close: '333.85001',
          official_close: '333.42999',
        },
        {
          date: '2026-07-31',
          timestamp: '2026-07-31 15:59:00',
          original_close: '309.029999',
          official_close: '308.91000',
        },
      ],
    },
    warmup_values: [
      { date: '2026-07-30 15:58:00', open: '333.50', high: '334.00', low: '333.10', close: '333.70000', volume: '1900' },
      { date: '2026-07-30 15:59:00', open: '333.70', high: '334.10', low: '333.20', close: '333.42999', volume: '2000' },
    ],
    values: [
      { date: '2026-07-31 15:58:00', open: '309.10', high: '309.80', low: '308.90', close: '309.64011', volume: '2100' },
      { date: '2026-07-31 15:59:00', open: '309.40', high: '309.70', low: '308.70', close: '308.91000', volume: '2200' },
    ],
  })

  const chart = buildDashboardPriceChart({
    security: selectedSecurity,
    marketData,
    range: '1D',
    requestedInterval: '1min',
  })

  assert.equal(chart.price, '$308.91')
  assert.equal(chart.change, '-$24.52')
  assert.equal(chart.percent, '-7.35%')
  assert.equal(chart.candles.at(-1).close, 308.91)
  assert.equal(chart.debug.previousCloseValue, 333.42999)
  assert.ok(Math.abs(chart.debug.dailyChangeValue - -24.51999) < 0.000001)
  assert.ok(Math.abs(chart.debug.dailyChangePercent - -7.353864599881958) < 0.000001)
  assert.equal(chart.indicators.length, chart.candles.length)
})

test('shows the last available OHLCV close with N/A change when only one candle is available', () => {
  const selectedSecurity = getActiveSecurities([
    security({ id: 1, symbol: 'AAPL', name: 'Apple Inc.' }),
  ])[0]
  const marketData = normalizeMarketData({
    security: security({ id: 1, symbol: 'AAPL' }),
    range: '1D',
    interval: '1min',
    source: 'TWELVE_DATA',
    values: [
      { date: '2026-07-29 15:59:00', open: '337.900000', high: '338.500000', low: '337.800000', close: '338.070000', volume: '1500' },
    ],
  })

  const chart = buildDashboardPriceChart({
    security: selectedSecurity,
    marketData,
    range: '1D',
    requestedInterval: '1min',
  })

  assert.equal(chart.price, '$338.07')
  assert.equal(chart.change, 'N/A')
  assert.equal(chart.percent, 'N/A')
  assert.equal(chart.quoteTone, 'neutral')
})

test('summarizes normalized market data without exposing provider credentials', () => {
  const response = {
    security: security({ id: 1, symbol: 'AAPL' }),
    range: '1D',
    interval: '1min',
    values: [
      { date: '2026-07-29 15:58:00', open: '337.10', high: '338.00', low: '337.00', close: '337.60', volume: '1400' },
      { date: '2026-07-29 15:59:00', open: '337.90', high: '338.50', low: '337.80', close: '338.070007', volume: '1500' },
    ],
  }
  const marketData = normalizeMarketData(response)
  const chart = buildDashboardPriceChart({
    security: getActiveSecurities([security({ id: 1, symbol: 'AAPL' })])[0],
    marketData,
    range: '1D',
    requestedInterval: '1min',
  })

  assert.deepEqual(getMarketDataDebugSummary({
    request: { securityId: 1, range: '1D', interval: '1min' },
    response,
    marketData,
    chart,
  }), {
    securityId: 1,
    symbol: 'AAPL',
    range: '1D',
    interval: '1min',
    apiCount: 2,
    warmupCount: 0,
    firstDatetime: '2026-07-29 15:58:00',
    firstClose: 337.6,
    lastDatetime: '2026-07-29 15:59:00',
    lastClose: 338.070007,
    chartCount: 2,
    chartLastClose: 338.070007,
    dailyApiLastRecord: { date: '2026-07-29 15:59:00', open: '337.90', high: '338.50', low: '337.80', close: '338.070007', volume: '1500' },
    normalizedLastRecord: { date: '2026-07-29 15:59:00', open: 337.9, high: 338.5, low: 337.8, close: 338.070007, volume: 1500 },
    fullDataLastRecord: { date: '2026-07-29 15:59:00', open: 337.9, high: 338.5, low: 337.8, close: 338.070007, volume: 1500 },
    visibleDataLastRecord: { date: '2026-07-29 15:59:00', open: 337.9, high: 338.5, low: 337.8, close: 338.070007, volume: 1500 },
    finalChartDataLastRecord: { date: '2026-07-29 15:59:00', open: 337.9, high: 338.5, low: 337.8, close: 338.070007, volume: 1500 },
    topPriceValue: 338.070007,
    topPriceSource: 'visibleData[visibleData.length - 1].close',
    previousClose: null,
    previousCloseSource: 'last fullData candle before latest marketDate',
    dailyChange: null,
    dailyChangePercent: null,
    provider: {},
    sessionCloseAdjustments: [],
  })
})

test('formats dashboard x-axis labels according to market-data interval', () => {
  assert.equal(formatDashboardDateLabel('2026-07-30 09:30:00', '1min', '1D'), '09:30')
  assert.equal(formatDashboardDateLabel('2026-07-30 10:00:00', '15min', '1W'), 'Jul 30, 10:00')
  assert.equal(formatDashboardDateLabel('2026-07-30 10:00:00', '2h', '1M'), 'Jul 30')
  assert.equal(formatDashboardDateLabel('2026-07-30', '1day', '1Y'), 'Jul 30')
})

test('builds empty chart state when backend returns no OHLCV values', () => {
  const selectedSecurity = getActiveSecurities([
    security({ id: 3, symbol: 'QQQ', name: 'Invesco QQQ ETF', asset_type: 'ETF' }),
  ])[0]

  const chart = buildDashboardPriceChart({
    security: selectedSecurity,
    marketData: normalizeMarketData({ range: '1Y', values: [] }),
    range: '1Y',
  })

  assert.equal(chart.symbol, 'QQQ')
  assert.equal(chart.price, 'OHLCV unavailable')
  assert.equal(chart.isEmpty, true)
})

test('builds error chart state without carrying over previous market data', () => {
  const selectedSecurity = getActiveSecurities([
    security({ id: 1, symbol: 'AAPL', name: 'Apple Inc.' }),
  ])[0]

  const chart = buildDashboardPriceChart({
    security: selectedSecurity,
    marketData: null,
    range: '1D',
    requestedInterval: '1min',
    error: 'Unable to load market data. Please try again.',
  })

  assert.equal(chart.candles.length, 0)
  assert.equal(chart.indicators.length, 0)
  assert.equal(chart.price, 'OHLCV unavailable')
  assert.equal(chart.error, 'Unable to load market data. Please try again.')
})

test('builds Custom market data request params with explicit dates', () => {
  const selectedSecurity = getActiveSecurities([
    security({ id: 9, symbol: 'SPY', name: 'SPDR S&P 500 ETF', asset_type: 'ETF' }),
  ])[0]

  assert.deepEqual(buildMarketDataRequestParams({
    security: selectedSecurity,
    range: 'Custom',
    interval: '1day',
    customRange: { startDate: '2026-01-05', endDate: '2026-01-10', interval: '30min' },
  }), {
    securityId: 9,
    range: 'Custom',
    interval: '30min',
    startDate: '2026-01-05',
    endDate: '2026-01-10',
  })
})

test('validates Custom range dates before requesting market data', () => {
  assert.deepEqual(
    createDefaultCustomMarketDataRange(new Date(2026, 6, 30)),
    { startDate: '2026-06-30', endDate: '2026-07-30', interval: '1h' },
  )
  assert.equal(
    validateCustomMarketDataRange({ startDate: '2026-01-05', endDate: '2026-01-10', interval: '15min' }, '2026-07-30'),
    '',
  )
  assert.match(
    validateCustomMarketDataRange({ startDate: '2026-01-11', endDate: '2026-01-10', interval: '30min' }, '2026-07-30'),
    /Start date/,
  )
  assert.match(
    validateCustomMarketDataRange({ startDate: '2026-01-05', endDate: '2026-08-01', interval: '30min' }, '2026-07-30'),
    /future/,
  )
  assert.match(
    validateCustomMarketDataRange({ startDate: '2025-01-05', endDate: '2026-01-10', interval: '30min' }, '2026-07-30'),
    /too large/,
  )
})

test('maps dashboard ranges to default intervals while allowing explicit interval requests', () => {
  assert.equal(getDefaultMarketDataInterval('1D'), '1min')
  assert.equal(getDefaultMarketDataInterval('1W'), '15min')
  assert.equal(getDefaultMarketDataInterval('1M'), '1h')
  assert.equal(getDefaultMarketDataInterval('3M'), '2h')
  assert.equal(getDefaultMarketDataInterval('5Y'), '1week')
  assert.equal(estimateMarketDataPoints('2026-01-01', '2026-01-10', '15min'), 960)
  assert.ok(Math.abs(estimateMarketDataPoints('2026-01-01', '2026-01-10', '1week') - (10 / 7)) < 0.000001)
})

test('calculates MACD and RSI series from real OHLCV candles', () => {
  const candles = Array.from({ length: 40 }, (_, index) => ({
    date: `2026-07-${String((index % 28) + 1).padStart(2, '0')}`,
    open: 100 + index,
    high: 102 + index,
    low: 99 + index,
    close: 101 + index,
    volume: 1000 + index,
  }))
  const indicators = buildDashboardIndicators(candles)

  assert.equal(indicators.length, candles.length)
  assert.equal(Number.isFinite(indicators.at(-1).macd), true)
  assert.equal(Number.isFinite(indicators.at(-1).signal), true)
  assert.equal(Number.isFinite(indicators.at(-1).histogram), true)
  assert.equal(Number.isFinite(indicators.at(-1).rsi), true)
})

test('builds dashboard technical indicator card values from chart OHLCV', () => {
  const selectedSecurity = getActiveSecurities([
    security({ id: 1, symbol: 'AAPL', name: 'Apple Inc.' }),
  ])[0]
  const candles = Array.from({ length: 45 }, (_, index) => ({
    date: `2026-07-${String((index % 28) + 1).padStart(2, '0')}`,
    open: 100 + index,
    high: 102 + index,
    low: 99 + index,
    close: 101 + index,
    volume: 1000 + index,
  }))
  const chart = buildDashboardPriceChart({
    security: selectedSecurity,
    marketData: {
      range: '3M',
      interval: '1day',
      isStale: false,
      visibleData: candles,
      fullData: candles,
      candles,
      warmupCandles: [],
    },
    range: '3M',
    requestedInterval: '1day',
  })

  const indicators = buildDashboardTechnicalIndicators(chart)

  assert.equal(indicators.sourceLabel, 'Real OHLCV signal snapshot')
  assert.notEqual(indicators.score, 72)
  assert.equal(indicators.items.length, 4)
  assert.equal(indicators.items[0].name, 'RSI (14)')
  assert.equal(Number.isFinite(Number(indicators.items[0].value)), true)
  assert.equal(indicators.items[2].name, 'Moving Avg. (20)')
  assert.match(indicators.items[2].value, /^\$/)
})

test('uses warm-up candles for 1D 1-minute MACD and RSI without displaying them', () => {
  const selectedSecurity = getActiveSecurities([
    security({ id: 2, symbol: 'MSFT', name: 'Microsoft Corporation' }),
  ])[0]
  const allCandles = Array.from({ length: 73 }, (_, index) => ({
    date: `2026-07-30 ${String(Math.floor(index / 2)).padStart(2, '0')}:${index % 2 === 0 ? '00' : '30'}:00`,
    open: 100 + index * 0.2,
    high: 101 + index * 0.2,
    low: 99 + index * 0.2,
    close: 100.5 + index * 0.2,
    volume: 1000 + index,
  }))
  const warmupCandles = allCandles.slice(0, 60)
  const visibleCandles = allCandles.slice(60)
  const indicators = buildDashboardIndicators(visibleCandles, warmupCandles)
  const chart = buildDashboardPriceChart({
    security: selectedSecurity,
    marketData: {
      range: '1D',
      interval: '1min',
      isStale: false,
      candles: visibleCandles,
      warmupCandles,
    },
    range: '1D',
    requestedInterval: '1min',
  })

  assert.equal(indicators.length, visibleCandles.length)
  assert.equal(chart.candles.length, 13)
  assert.equal(chart.candles[0].date, visibleCandles[0].date)
  assert.equal(Number.isFinite(indicators.at(-1).macd), true)
  assert.equal(Number.isFinite(indicators.at(-1).signal), true)
  assert.equal(Number.isFinite(indicators.at(-1).histogram), true)
  assert.equal(Number.isFinite(indicators.at(-1).rsi), true)
  assert.equal(chart.indicatorWarnings.macd, '')
  assert.equal(chart.indicatorWarnings.rsi, '')
})

test('reports insufficient indicator history without warm-up candles', () => {
  const selectedSecurity = getActiveSecurities([
    security({ id: 4, symbol: 'AMZN', name: 'Amazon.com Inc.' }),
  ])[0]
  const visibleCandles = Array.from({ length: 13 }, (_, index) => ({
    date: `2026-07-30 ${String(index + 9).padStart(2, '0')}:30:00`,
    open: 100 + index,
    high: 102 + index,
    low: 99 + index,
    close: 101 + index,
    volume: 1000 + index,
  }))
  const chart = buildDashboardPriceChart({
    security: selectedSecurity,
    marketData: {
      range: '1D',
      interval: '1min',
      isStale: false,
      candles: visibleCandles,
      warmupCandles: [],
    },
    range: '1D',
    requestedInterval: '1min',
  })

  assert.equal(chart.indicatorWarnings.macd, 'Insufficient historical data for MACD.')
  assert.equal(chart.indicatorWarnings.rsi, 'Insufficient historical data for RSI.')
})

test('formats candlestick tooltip from real OHLCV values', () => {
  const tooltip = formatDashboardCandleTooltip({
    date: '2026-07-24',
    open: 100,
    high: 108.125,
    low: 98.5,
    close: 104,
    volume: 1234567,
  }, 'USD')

  assert.equal(tooltip.date, '2026-07-24')
  assert.equal(tooltip.open, '$100.00')
  assert.equal(tooltip.high, '$108.13')
  assert.equal(tooltip.low, '$98.50')
  assert.equal(tooltip.close, '$104.00')
  assert.equal(tooltip.change, '+$4.00')
  assert.equal(tooltip.changePercent, '+4.00%')
  assert.equal(tooltip.volume, '1.2M')
  assert.equal(tooltip.tone, 'up')
})

test('ignores stale market data responses from older range requests', () => {
  assert.equal(shouldApplyMarketDataResponse(4, 4), true)
  assert.equal(shouldApplyMarketDataResponse(5, 4), false)
})

test('zooms a short 1D 1-minute viewport instead of blocking at 20 candles', () => {
  const fullWindow = normalizeDashboardVisibleWindow(null, 13)
  const zoomedWindow = zoomDashboardVisibleWindow({
    window: fullWindow,
    total: 13,
    anchorRatio: 0.5,
    deltaY: -100,
  })
  const zoomedSize = zoomedWindow.end - zoomedWindow.start + 1

  assert.deepEqual(fullWindow, { start: 0, end: 12 })
  assert.equal(zoomedSize, 10)
  assert.ok(zoomedWindow.start >= 0)
  assert.ok(zoomedWindow.end <= 12)

  const resetWindow = normalizeDashboardVisibleWindow(null, 13)
  assert.deepEqual(resetWindow, { start: 0, end: 12 })
})

test('mouse wheel zoom reduces and restores long-range visible candles without API state', () => {
  const fullWindow = normalizeDashboardVisibleWindow(null, 252)
  const zoomedWindow = zoomDashboardVisibleWindow({
    window: fullWindow,
    total: 252,
    anchorRatio: 0.75,
    deltaY: -120,
  })
  const restoredWindow = zoomDashboardVisibleWindow({
    window: zoomedWindow,
    total: 252,
    anchorRatio: 0.75,
    deltaY: 1200,
  })

  assert.equal(fullWindow.end - fullWindow.start + 1, 252)
  assert.ok(zoomedWindow.end - zoomedWindow.start + 1 < 252)
  assert.ok(zoomedWindow.end <= 251)
  assert.ok(restoredWindow.end - restoredWindow.start + 1 > zoomedWindow.end - zoomedWindow.start + 1)
})

test('pans the shared chart viewport within loaded data bounds', () => {
  const zoomedWindow = clampDashboardVisibleWindow(40, 89, 120)
  const earlierWindow = panDashboardVisibleWindow({
    window: zoomedWindow,
    total: 120,
    shift: -25,
  })
  const latestWindow = panDashboardVisibleWindow({
    window: zoomedWindow,
    total: 120,
    shift: 1000,
  })

  assert.deepEqual(earlierWindow, { start: 15, end: 64 })
  assert.deepEqual(latestWindow, { start: 70, end: 119 })
})
