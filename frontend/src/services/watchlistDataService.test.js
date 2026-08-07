import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildWatchlistStock,
  buildWatchlistTechnicalStatus,
} from './watchlistDataService.js'

function makeSecurity(overrides = {}) {
  return {
    id: 1,
    symbol: 'AAPL',
    name: 'Apple Inc.',
    asset_type: 'STOCK',
    currency: 'USD',
    is_active: true,
    ...overrides,
  }
}

function makeClosePoints(values) {
  return values.map((close, index) => ({
    date: `2026-07-${String(index + 1).padStart(2, '0')}`,
    close,
  }))
}

test('buildWatchlistTechnicalStatus uses real close history for RSI, MACD, and overall trend', () => {
  const risingCloses = Array.from({ length: 80 }, (_, index) => 100 + index + (index ** 2) * 0.05)
  const fallingCloses = Array.from({ length: 80 }, (_, index) => 500 - index - (index ** 2) * 0.05)

  const bullish = buildWatchlistTechnicalStatus(risingCloses, risingCloses.at(-1))
  const bearish = buildWatchlistTechnicalStatus(fallingCloses, fallingCloses.at(-1))

  assert.equal(bullish.rsiStatus, 'Overbought')
  assert.equal(bullish.macdStatus, 'Bullish')
  assert.equal(bullish.overallTrend, 'Uptrend')
  assert.equal(bearish.rsiStatus, 'Oversold')
  assert.equal(bearish.macdStatus, 'Bearish')
  assert.equal(bearish.overallTrend, 'Downtrend')
})

test('buildWatchlistStock uses summary quote and real mini trend points', () => {
  const closes = Array.from({ length: 80 }, (_, index) => 100 + index + (index ** 2) * 0.05)
  const stock = buildWatchlistStock(makeSecurity(), 10, {
    item_id: 10,
    quote: {
      price: '198.120000',
      change: '1.500000',
      percent_change: '0.760000',
      currency: 'USD',
      as_of: '2026-07-31',
      data_status: 'ok',
    },
    history: {
      mini_trend: makeClosePoints([194, 195.5, 198.12]),
      indicator_closes: makeClosePoints(closes),
      data_status: 'ok',
    },
  })

  assert.equal(stock.price, 198.12)
  assert.equal(stock.dailyChange, 1.5)
  assert.deepEqual(stock.trend, [194, 195.5, 198.12])
  assert.equal(stock.latestAsOf, '2026-07-31')
  assert.equal(stock.rsiStatus, 'Overbought')
  assert.equal(stock.macdStatus, 'Bullish')
  assert.equal(stock.overallTrend, 'Uptrend')
})

test('buildWatchlistStock does not invent a fake mini trend when history is unavailable', () => {
  const stock = buildWatchlistStock(makeSecurity(), 10, {
    item_id: 10,
    quote: {
      price: null,
      change: null,
      percent_change: null,
      currency: 'USD',
      data_status: 'unavailable',
      error: 'Market data provider rate limit reached.',
    },
    history: {
      mini_trend: [],
      indicator_closes: [],
      data_status: 'unavailable',
      error: 'Market data provider rate limit reached.',
    },
  })

  assert.equal(stock.price, null)
  assert.deepEqual(stock.trend, [])
  assert.equal(stock.rsiStatus, 'N/A')
  assert.equal(stock.macdStatus, 'N/A')
  assert.equal(stock.overallTrend, 'N/A')
})
