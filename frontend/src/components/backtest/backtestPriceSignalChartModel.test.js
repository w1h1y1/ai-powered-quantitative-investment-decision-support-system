import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getBacktestAxisDateDetail,
  getBacktestChartTickIndices,
  getVisibleBacktestChartData,
  getVisibleBacktestPoints,
  layoutBacktestTradeMarkers,
} from './backtestPriceSignalChartModel.js'

function buildPoints(count = 20) {
  return Array.from({ length: count }, (_, index) => ({
    date: `2026-04-${String(index + 1).padStart(2, '0')}`,
    close: 100 + index,
    swingAverage: 99 + index,
    ma20: 98 + index,
    ma60: 97 + index,
  }))
}

test('zoomed Backtest window slices every series and remaps trades to the same local date index', () => {
  const points = buildPoints()
  const trades = [
    { id: 'before', executionDate: '2026-04-03', price: 102 },
    { id: 'visible', executionDate: '2026-04-08', price: 107 },
    { id: 'after', executionDate: '2026-04-18', price: 117 },
  ]

  const result = getVisibleBacktestChartData(points, trades, { start: 5, end: 10 })

  assert.equal(result.visiblePoints[0].date, '2026-04-06')
  assert.equal(result.visiblePoints.at(-1).date, '2026-04-11')
  assert.deepEqual(result.visibleTrades.map((trade) => trade.id), ['visible'])
  assert.equal(result.visibleTrades[0].pointIndex, 2)
})

test('generic Backtest time-series windows keep the inclusive first and last visible dates', () => {
  const points = Array.from({ length: 20 }, (_, index) => ({ date: `2026-06-${String(index + 1).padStart(2, '0')}` }))

  const { visiblePoints, window } = getVisibleBacktestPoints(points, { start: 14, end: 19 })

  assert.deepEqual(window, { start: 14, end: 19 })
  assert.equal(visiblePoints[0].date, '2026-06-15')
  assert.equal(visiblePoints.at(-1).date, '2026-06-20')
})

test('marker layout offsets rendering without changing the real execution price anchor', () => {
  const markers = layoutBacktestTradeMarkers({
    trades: [
      { id: 'core-buy', pointIndex: 4, price: 100, positionLayer: 'CORE', type: 'BUY' },
      { id: 'swing-buy', pointIndex: 4, price: 100, positionLayer: 'SWING', type: 'BUY' },
      { id: 'core-exit', pointIndex: 4, price: 100, positionLayer: 'CORE', type: 'SELL' },
    ],
    xScale: () => 200,
    yScale: () => 100,
    plotTop: 10,
    plotBottom: 300,
  })

  assert.ok(markers.every((marker) => marker.actualY === 100 && marker.price === 100))
  assert.ok(markers[0].markerY < markers[0].actualY)
  assert.ok(markers[1].markerY < markers[1].actualY)
  assert.ok(markers[2].markerY > markers[2].actualY)
  assert.ok(Math.abs(markers[0].markerY - markers[1].markerY) >= 13)
  assert.ok(markers[1].collisionLane > 0)
})

test('x-axis tick density stays compact and switches to detailed dates when zoomed', () => {
  assert.equal(getBacktestChartTickIndices(252).length, 7)
  assert.deepEqual(getBacktestChartTickIndices(1), [0])
  assert.equal(getBacktestAxisDateDetail(buildPoints(20)), 'day')
  assert.equal(getBacktestAxisDateDetail([
    { date: '2024-01-01' },
    { date: '2026-01-01' },
  ]), 'month-year')
})
