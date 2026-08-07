import { useMemo, useState } from 'react'
import { createDefinedLinePath } from '../market-analysis/chartMath'
import {
  formatCompactCurrency,
  formatCurrency,
  formatQuantity,
} from '../portfolio/portfolioMath'

const chartWidth = 900
const chartHeight = 330
const chartPadding = { top: 24, right: 22, bottom: 38, left: 68 }

const axisDateFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  year: '2-digit',
  timeZone: 'UTC',
})

const tooltipDateFormatter = new Intl.DateTimeFormat('en-US', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

function formatDate(value, formatter) {
  return formatter.format(new Date(`${value}T00:00:00Z`))
}

function getTickIndices(pointCount) {
  const lastIndex = Math.max(pointCount - 1, 0)
  return [...new Set(Array.from({ length: 5 }, (_, index) => Math.round((lastIndex * index) / 4)))]
}

function formatReason(value) {
  return String(value || '').replaceAll('_', ' ')
}

function buildMarkerTitle(trade) {
  return [
    `Layer: ${trade.positionLayer}`,
    `Action: ${trade.action}`,
    `Reason: ${formatReason(trade.reason)}`,
    `Signal Date: ${trade.signalDate}`,
    `Execution Date: ${trade.executionDate}`,
    `Execution Price: ${formatCurrency(trade.price)}`,
    `Quantity: ${formatQuantity(trade.quantity)}`,
    `Fee: ${formatCurrency(trade.fee)}`,
  ].join('\n')
}

function TradeMarker({ trade, x, y }) {
  const markerClass = `${trade.positionLayer.toLowerCase()}-${trade.type.toLowerCase()}`
  const isCore = trade.positionLayer === 'CORE'
  const isBuy = trade.type === 'BUY'

  return (
    <g className={`backtest-layer-trade-marker is-${markerClass}`}>
      <title>{buildMarkerTitle(trade)}</title>
      {isCore ? (
        <circle cx={x} cy={y} r="7.5" />
      ) : isBuy ? (
        <polygon points={`${x},${y - 8} ${x - 8},${y + 6} ${x + 8},${y + 6}`} />
      ) : (
        <rect x={x - 6} y={y - 6} width="12" height="12" transform={`rotate(45 ${x} ${y})`} />
      )}
      <text x={x} y={y + 2.5} textAnchor="middle">{isCore ? (isBuy ? 'C+' : 'C-') : (isBuy ? 'S+' : 'S-')}</text>
    </g>
  )
}

export default function BacktestPriceSignalChart({ points = [], trades = [], coreFastMa, coreSlowMa, swingAverageType = 'EMA10' }) {
  const [hoveredPoint, setHoveredPoint] = useState(null)

  const geometry = useMemo(() => {
    if (!points.length) return null
    const finitePrices = points.flatMap((point) => [point.close, point.swingAverage, point.ma20, point.ma60])
      .filter(Number.isFinite)
    const executionPrices = trades.map((trade) => trade.price).filter(Number.isFinite)
    const values = [...finitePrices, ...executionPrices]
    if (!values.length) return null

    const rawMinimum = Math.min(...values)
    const rawMaximum = Math.max(...values)
    const pricePadding = Math.max((rawMaximum - rawMinimum) * 0.1, Math.abs(rawMaximum) * 0.01, 0.01)
    const minimum = Math.max(0, rawMinimum - pricePadding)
    const maximum = rawMaximum + pricePadding
    const valueRange = maximum - minimum || 1
    const plotWidth = chartWidth - chartPadding.left - chartPadding.right
    const plotHeight = chartHeight - chartPadding.top - chartPadding.bottom
    const xScale = (index) => chartPadding.left + (index / Math.max(points.length - 1, 1)) * plotWidth
    const yScale = (value) => chartPadding.top + ((maximum - value) / valueRange) * plotHeight
    const dateIndices = new Map(points.map((point, index) => [point.date, index]))
    const tradeMarkers = trades
      .map((trade) => ({ ...trade, pointIndex: dateIndices.get(trade.executionDate) }))
      .filter((trade) => Number.isInteger(trade.pointIndex) && Number.isFinite(trade.price))

    return {
      xScale,
      yScale,
      yTicks: Array.from({ length: 5 }, (_, index) => maximum - (valueRange * index) / 4),
      tickIndices: getTickIndices(points.length),
      plotBottom: chartPadding.top + plotHeight,
      closePath: createDefinedLinePath(points.map((point) => point.close), xScale, yScale),
      swingAveragePath: createDefinedLinePath(points.map((point) => point.swingAverage), xScale, yScale),
      ma20Path: createDefinedLinePath(points.map((point) => point.ma20), xScale, yScale),
      ma60Path: createDefinedLinePath(points.map((point) => point.ma60), xScale, yScale),
      tradeMarkers,
    }
  }, [points, trades])

  const tradesByDate = useMemo(() => {
    const groupedTrades = new Map()
    trades.forEach((trade) => {
      if (!trade.executionDate) return
      groupedTrades.set(trade.executionDate, [...(groupedTrades.get(trade.executionDate) ?? []), trade])
    })
    return groupedTrades
  }, [trades])

  const handlePointerMove = (event) => {
    if (!geometry || !points.length) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const plotLeft = (chartPadding.left / chartWidth) * bounds.width
    const plotRight = (chartPadding.right / chartWidth) * bounds.width
    const plotWidth = Math.max(bounds.width - plotLeft - plotRight, 1)
    const pointerX = Math.min(Math.max(event.clientX - bounds.left, plotLeft), plotLeft + plotWidth)
    const progress = (pointerX - plotLeft) / plotWidth
    setHoveredPoint({
      index: Math.round(progress * Math.max(points.length - 1, 0)),
      x: pointerX,
      y: Math.min(Math.max(event.clientY - bounds.top, 78), Math.max(bounds.height - 78, 78)),
      alignLeft: progress > 0.68,
    })
  }

  const activePoint = hoveredPoint ? points[hoveredPoint.index] : null
  const activeTrades = activePoint ? tradesByDate.get(activePoint.date) ?? [] : []
  const series = [
    ['close', 'is-close'],
    ['swingAverage', 'is-ma10'],
    ['ma20', 'is-ma20'],
    ['ma60', 'is-ma60'],
  ]

  return (
    <section className="backtest-card backtest-chart-card backtest-price-signal-card" aria-labelledby="backtest-price-signals-title">
      <div className="backtest-card-header">
        <div>
          <p>Layered strategy execution</p>
          <h2 id="backtest-price-signals-title">Price &amp; Strategy Signals</h2>
          <span>Historical close, trend averages and independently executed Core and Swing orders.</span>
        </div>
      </div>

      <div className="backtest-chart-legend" aria-label="Price and strategy signals legend">
        <span><i className="is-close-price" aria-hidden="true" />Close</span>
        <span><i className="is-ma10" aria-hidden="true" />{swingAverageType}</span>
        <span><i className="is-fast-ma" aria-hidden="true" />MA{coreFastMa}</span>
        <span><i className="is-slow-ma" aria-hidden="true" />MA{coreSlowMa}</span>
        <span><i className="is-core-buy" aria-hidden="true" />Core BUY</span>
        <span><i className="is-core-exit" aria-hidden="true" />Core EXIT</span>
        <span><i className="is-swing-buy" aria-hidden="true" />Swing BUY</span>
        <span><i className="is-swing-sell" aria-hidden="true" />Swing SELL</span>
      </div>

      {geometry ? (
        <div
          className="backtest-line-chart backtest-price-signal-chart"
          onPointerMove={handlePointerMove}
          onPointerLeave={() => setHoveredPoint(null)}
          onPointerCancel={() => setHoveredPoint(null)}
        >
          <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} preserveAspectRatio="none" role="img" aria-label={`Close, ${swingAverageType}, Core moving averages and Core and Swing trade markers`}>
            {geometry.yTicks.map((tick, index) => {
              const y = geometry.yScale(tick)
              return (
                <g key={`price-y-${index}`}>
                  <line className="backtest-chart-grid-line" x1={chartPadding.left} x2={chartWidth - chartPadding.right} y1={y} y2={y} />
                  <text className="backtest-chart-axis-label" x={chartPadding.left - 10} y={y + 3} textAnchor="end">{formatCompactCurrency(tick)}</text>
                </g>
              )
            })}
            {geometry.tickIndices.map((index, tickPosition) => (
              <text
                className="backtest-chart-axis-label"
                x={geometry.xScale(index)}
                y={chartHeight - 11}
                textAnchor={tickPosition === 0 ? 'start' : tickPosition === geometry.tickIndices.length - 1 ? 'end' : 'middle'}
                key={`price-x-${points[index].date}`}
              >
                {formatDate(points[index].date, axisDateFormatter)}
              </text>
            ))}
            <path className="backtest-close-price-line" d={geometry.closePath} />
            <path className="backtest-ma10-line" d={geometry.swingAveragePath} />
            <path className="backtest-fast-ma-line" d={geometry.ma20Path} />
            <path className="backtest-slow-ma-line" d={geometry.ma60Path} />
            {geometry.tradeMarkers.map((trade) => (
              <TradeMarker trade={trade} x={geometry.xScale(trade.pointIndex)} y={geometry.yScale(trade.price)} key={trade.id} />
            ))}
            {hoveredPoint && activePoint && (
              <>
                <line className="backtest-chart-hover-line" x1={geometry.xScale(hoveredPoint.index)} x2={geometry.xScale(hoveredPoint.index)} y1={chartPadding.top} y2={geometry.plotBottom} />
                {series.map(([key, className]) => Number.isFinite(activePoint[key]) && (
                  <circle className={`backtest-chart-hover-point ${className}`} cx={geometry.xScale(hoveredPoint.index)} cy={geometry.yScale(activePoint[key])} r="3.7" key={key} />
                ))}
              </>
            )}
          </svg>

          {hoveredPoint && activePoint && (
            <div className={`backtest-chart-tooltip backtest-price-signal-tooltip${hoveredPoint.alignLeft ? ' is-left' : ''}`} style={{ left: hoveredPoint.x, top: hoveredPoint.y }} role="tooltip">
              <strong>{formatDate(activePoint.date, tooltipDateFormatter)}</strong>
              <span>Close <b>{Number.isFinite(activePoint.close) ? formatCurrency(activePoint.close) : '-'}</b></span>
              <span>{swingAverageType} <b>{Number.isFinite(activePoint.swingAverage) ? formatCurrency(activePoint.swingAverage) : '-'}</b></span>
              <span>MA{coreFastMa} <b>{Number.isFinite(activePoint.ma20) ? formatCurrency(activePoint.ma20) : '-'}</b></span>
              <span>MA{coreSlowMa} <b>{Number.isFinite(activePoint.ma60) ? formatCurrency(activePoint.ma60) : '-'}</b></span>
              {activeTrades.map((trade) => (
                <div className={`backtest-tooltip-trade is-${trade.type.toLowerCase()}`} key={trade.id}>
                  <strong>{trade.positionLayer} {trade.action}</strong>
                  <span>Reason <b>{formatReason(trade.reason)}</b></span>
                  <span>Signal Date <b>{trade.signalDate}</b></span>
                  <span>Execution Date <b>{trade.executionDate}</b></span>
                  <span>Execution Price <b>{formatCurrency(trade.price)}</b></span>
                  <span>Quantity <b>{formatQuantity(trade.quantity)}</b></span>
                  <span>Fee <b>{formatCurrency(trade.fee)}</b></span>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="backtest-chart-empty" role="status">
          <strong>Price data is not available in this result.</strong>
          <span>Run the strategy again to load real price, moving-average and layered trade data.</span>
        </div>
      )}
    </section>
  )
}
