import { normalizeDashboardVisibleWindow } from '../dashboard/dashboardSecurityModel.js'

export const backtestMinimumVisiblePoints = 12

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum)
}

export function getVisibleBacktestPoints(points = [], visibleWindow = null) {
  const window = normalizeDashboardVisibleWindow(visibleWindow, points.length)
  const visiblePoints = points.slice(window.start, window.end + 1)
  return { visiblePoints, window }
}

export function getVisibleBacktestChartData(points = [], trades = [], visibleWindow = null) {
  const { visiblePoints, window } = getVisibleBacktestPoints(points, visibleWindow)
  const dateIndices = new Map(visiblePoints.map((point, index) => [point.date, index]))
  const visibleTrades = trades
    .map((trade) => ({ ...trade, pointIndex: dateIndices.get(trade.executionDate) }))
    .filter((trade) => Number.isInteger(trade.pointIndex) && Number.isFinite(trade.price))

  return { visiblePoints, visibleTrades, window }
}

export function getBacktestChartTickIndices(pointCount, maximumTicks = 7) {
  const safeCount = Math.max(Math.floor(Number(pointCount) || 0), 0)
  if (!safeCount) return []
  if (safeCount === 1) return [0]

  const tickCount = Math.min(safeCount, maximumTicks)
  const lastIndex = safeCount - 1
  return [...new Set(Array.from(
    { length: tickCount },
    (_, index) => Math.round((lastIndex * index) / Math.max(tickCount - 1, 1)),
  ))]
}

function getMarkerDirection(trade) {
  return trade.type === 'BUY' ? -1 : 1
}

function getMarkerBaseOffset(trade) {
  return trade.positionLayer === 'CORE' ? 15 : 8
}

export function layoutBacktestTradeMarkers({
  trades = [],
  xScale,
  yScale,
  plotTop,
  plotBottom,
}) {
  const placedMarkers = []

  return trades.map((trade) => {
    const actualX = xScale(trade.pointIndex)
    const actualY = yScale(trade.price)
    const direction = getMarkerDirection(trade)
    const isCore = trade.positionLayer === 'CORE'
    const markerRadius = isCore ? 7 : 5
    const markerX = actualX + (isCore ? 0 : trade.type === 'BUY' ? -1.5 : 1.5)
    let markerY = actualY + direction * getMarkerBaseOffset(trade)
    let collisionLane = 0

    while (
      collisionLane < 4
      && placedMarkers.some((marker) => (
        Math.abs(marker.markerX - markerX) < 13
        && Math.abs(marker.markerY - markerY) < 13
      ))
    ) {
      collisionLane += 1
      markerY += direction * 9
    }

    markerY = clamp(markerY, plotTop + markerRadius, plotBottom - markerRadius)
    const marker = {
      ...trade,
      actualX,
      actualY,
      collisionLane,
      markerX,
      markerY,
    }
    placedMarkers.push(marker)
    return marker
  })
}

export function getBacktestAxisDateDetail(points = []) {
  if (points.length < 2) return 'day'
  const firstTime = Date.parse(`${points[0].date}T00:00:00Z`)
  const lastTime = Date.parse(`${points.at(-1).date}T00:00:00Z`)
  const spanDays = Number.isFinite(firstTime) && Number.isFinite(lastTime)
    ? Math.max(Math.round((lastTime - firstTime) / 86400000), 0)
    : points.length

  if (spanDays <= 100) return 'day'
  if (spanDays <= 365) return 'month-day'
  return 'month-year'
}
