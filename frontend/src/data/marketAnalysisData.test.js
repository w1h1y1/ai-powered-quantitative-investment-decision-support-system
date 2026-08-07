import assert from 'node:assert/strict'
import test from 'node:test'

import { getMarketHistory } from './marketAnalysisData.js'

function stockWithCandles(candles) {
  return {
    history: {
      '1D': {
        '30m': {
          candles,
          labels: ['09:30', '16:00'],
        },
      },
    },
  }
}

test('market analysis history is sorted ascending before selecting the latest candle', () => {
  const history = getMarketHistory(stockWithCandles([
    {
      id: 'latest',
      timestamp: Date.UTC(2026, 6, 29, 15, 59),
      open: '337.90',
      high: '338.50',
      low: '337.80',
      close: '338.070000',
      volume: '1500',
    },
    {
      id: 'previous',
      timestamp: Date.UTC(2026, 6, 29, 15, 58),
      open: '337.10',
      high: '338.00',
      low: '337.00',
      close: '337.600000',
      volume: '1400',
    },
  ]), {
    range: '1D',
    interval: '30m',
  })

  assert.deepEqual(history.candles.map((candle) => candle.id), ['previous', 'latest'])
  assert.deepEqual(history.closes, [337.6, 338.07])
  assert.equal(history.candles.at(-1).close, 338.07)
})

test('market analysis history skips invalid candles without treating them as latest', () => {
  const history = getMarketHistory(stockWithCandles([
    {
      id: 'invalid-latest',
      timestamp: Date.UTC(2026, 6, 29, 16, 0),
      open: '338.00',
      high: '339.00',
      low: '337.50',
      close: '',
      volume: '1600',
    },
    {
      id: 'latest-valid',
      timestamp: Date.UTC(2026, 6, 29, 15, 59),
      open: '337.90',
      high: '338.50',
      low: '337.80',
      close: '338.070000',
      volume: '1500',
    },
  ]), {
    range: '1D',
    interval: '30m',
  })

  assert.deepEqual(history.candles.map((candle) => candle.id), ['latest-valid'])
  assert.equal(history.candles.at(-1).close, 338.07)
  assert.deepEqual(history.opens, [337.9])
  assert.deepEqual(history.volumes, [1500])
})
