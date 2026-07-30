import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildDashboardPriceChart,
  buildMarketDataRequestParams,
  createDefaultCustomMarketDataRange,
  dashboardMarketDataRanges,
  filterSecurityOptions,
  formatDashboardCandleTooltip,
  getActiveSecurities,
  normalizeMarketData,
  readStoredSecurityId,
  resolveSelectedSecurityId,
  shouldApplyMarketDataResponse,
  validateCustomMarketDataRange,
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
    isActive: true,
  }])
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

test('normalizes backend OHLCV response for candlestick rendering', () => {
  const marketData = normalizeMarketData({
    range: '3M',
    source: 'TWELVE_DATA',
    is_stale: false,
    values: [
      { date: '2026-07-23', open: '100.00', high: '105.00', low: '99.50', close: '104.00', volume: 123456 },
      { date: '2026-07-24', open: '104.00', high: '108.00', low: '103.00', close: '107.50', volume: '234567' },
    ],
  })

  assert.equal(marketData.range, '3M')
  assert.equal(marketData.source, 'TWELVE_DATA')
  assert.equal(marketData.candles.length, 2)
  assert.equal(marketData.candles[1].close, 107.5)
  assert.equal(marketData.candles[1].volume, 234567)
})

test('builds dashboard chart from selected Security plus real backend OHLCV', () => {
  const selectedSecurity = getActiveSecurities([
    security({ id: 2, symbol: 'MSFT', name: 'Microsoft Corporation' }),
  ])[0]
  const marketData = normalizeMarketData({
    range: '3M',
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
  assert.deepEqual(chart.ranges, ['1M', '3M', '6M', 'YTD', '1Y', '3Y', '5Y', 'Custom'])
  assert.equal(chart.symbol, 'MSFT')
  assert.equal(chart.currency, 'USD')
  assert.equal(chart.price, '$107.50')
  assert.equal(chart.change, '+$3.50')
  assert.equal(chart.percent, '+3.37%')
  assert.equal(chart.candles.length, 2)
  assert.match(chart.dataSourceNote, /Twelve Data daily OHLCV/)
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

test('builds Custom market data request params with explicit dates', () => {
  const selectedSecurity = getActiveSecurities([
    security({ id: 9, symbol: 'SPY', name: 'SPDR S&P 500 ETF', asset_type: 'ETF' }),
  ])[0]

  assert.deepEqual(buildMarketDataRequestParams({
    security: selectedSecurity,
    range: 'Custom',
    customRange: { startDate: '2026-01-05', endDate: '2026-01-10' },
  }), {
    securityId: 9,
    range: 'Custom',
    startDate: '2026-01-05',
    endDate: '2026-01-10',
  })
})

test('validates Custom range dates before requesting market data', () => {
  assert.deepEqual(
    createDefaultCustomMarketDataRange(new Date(2026, 6, 30)),
    { startDate: '2026-06-30', endDate: '2026-07-30' },
  )
  assert.equal(
    validateCustomMarketDataRange({ startDate: '2026-01-05', endDate: '2026-01-10' }, '2026-07-30'),
    '',
  )
  assert.match(
    validateCustomMarketDataRange({ startDate: '2026-01-11', endDate: '2026-01-10' }, '2026-07-30'),
    /Start date/,
  )
  assert.match(
    validateCustomMarketDataRange({ startDate: '2026-01-05', endDate: '2026-08-01' }, '2026-07-30'),
    /future/,
  )
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
