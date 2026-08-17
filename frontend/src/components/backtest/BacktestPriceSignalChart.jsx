import { useEffect, useId, useMemo, useState } from 'react'
import { createDefinedLinePath } from '../market-analysis/chartMath'
import {
  formatCompactCurrency,
  formatCurrency,
  formatQuantity,
} from '../portfolio/portfolioMath'
import {
  getBacktestAxisDateDetail,
  getBacktestChartTickIndices,
  getVisibleBacktestChartData,
  layoutBacktestTradeMarkers,
} from './backtestPriceSignalChartModel'
import useBacktestChartViewport from './useBacktestChartViewport'

const chartWidth = 900
const chartHeight = 320
const chartPadding = { top: 18, right: 22, bottom: 38, left: 68 }
const plotWidth = chartWidth - chartPadding.left - chartPadding.right
const plotHeight = chartHeight - chartPadding.top - chartPadding.bottom

const axisFormatters = {
  day: new Intl.DateTimeFormat('en-US', {
    day: '2-digit',
    month: 'short',
    timeZone: 'UTC',
  }),
  'month-day': new Intl.DateTimeFormat('en-US', {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  }),
  'month-year': new Intl.DateTimeFormat('en-US', {
    month: 'short',
    year: '2-digit',
    timeZone: 'UTC',
  }),
}

const tooltipDateFormatter = new Intl.DateTimeFormat('en-US', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum)
}

function formatDate(value, formatter) {
  return formatter.format(new Date(`${value}T00:00:00Z`))
}

function formatReason(value) {
  return String(value || '').replaceAll('_', ' ')
}

function getLayerLabel(trade) {
  return trade.positionLayer === 'CORE' ? 'Core' : 'Swing'
}

function getTradeHeading(trade) {
  const action = trade.positionLayer === 'CORE' && trade.type === 'SELL' ? 'EXIT' : trade.type
  return `${getLayerLabel(trade)} ${action}`
}

function buildMarkerTitle(trade) {
  return [
    getTradeHeading(trade),
    trade.executionDate && `Date: ${trade.executionDate}`,
    Number.isFinite(trade.price) && `Price: ${formatCurrency(trade.price)}`,
    trade.type && `Action: ${trade.type}`,
    `Layer: ${getLayerLabel(trade)}`,
    Number.isFinite(trade.quantity) && `Quantity: ${formatQuantity(trade.quantity)}`,
    trade.reason && `Reason: ${formatReason(trade.reason)}`,
  ].filter(Boolean).join('\n')
}

function TradeMarker({ marker, onHover, onLeave }) {
  const markerClass = `${marker.positionLayer.toLowerCase()}-${marker.type.toLowerCase()}`
  const isCore = marker.positionLayer === 'CORE'
  const isBuy = marker.type === 'BUY'
  const corePoints = isBuy
    ? `${marker.markerX},${marker.markerY - 7} ${marker.markerX - 7},${marker.markerY + 6} ${marker.markerX + 7},${marker.markerY + 6}`
    : `${marker.markerX - 7},${marker.markerY - 6} ${marker.markerX + 7},${marker.markerY - 6} ${marker.markerX},${marker.markerY + 7}`

  return (
    <g
      className={`backtest-layer-trade-marker is-${markerClass}`}
      role="img"
      aria-label={buildMarkerTitle(marker)}
      onPointerEnter={(event) => onHover(marker, event)}
      onPointerMove={(event) => onHover(marker, event)}
      onPointerLeave={onLeave}
    >
      <title>{buildMarkerTitle(marker)}</title>
      <line
        className="backtest-trade-marker-guide"
        x1={marker.actualX}
        x2={marker.markerX}
        y1={marker.actualY}
        y2={marker.markerY}
      />
      <circle className="backtest-trade-marker-hit-area" cx={marker.markerX} cy={marker.markerY} r="11" />
      {isCore ? (
        <polygon className="backtest-trade-marker-shape" points={corePoints} />
      ) : (
        <rect
          className="backtest-trade-marker-shape"
          x={marker.markerX - 4.5}
          y={marker.markerY - 4.5}
          width="9"
          height="9"
          transform={`rotate(45 ${marker.markerX} ${marker.markerY})`}
        />
      )}
    </g>
  )
}

function TradeTooltipDetails({ trade }) {
  return (
    <div className={`backtest-tooltip-trade is-${trade.type.toLowerCase()}`}>
      <strong>{getTradeHeading(trade)}</strong>
      {trade.executionDate && <span>Date <b>{trade.executionDate}</b></span>}
      {Number.isFinite(trade.price) && <span>Price <b>{formatCurrency(trade.price)}</b></span>}
      {trade.type && <span>Action <b>{trade.type}</b></span>}
      <span>Layer <b>{getLayerLabel(trade)}</b></span>
      {Number.isFinite(trade.quantity) && <span>Quantity <b>{formatQuantity(trade.quantity)}</b></span>}
      {trade.reason && <span>Reason <b>{formatReason(trade.reason)}</b></span>}
    </div>
  )
}

export default function BacktestPriceSignalChart({
  points = [],
  trades = [],
  coreFastMa,
  coreSlowMa,
  swingAverageType = 'EMA10',
}) {
  const [hoveredPoint, setHoveredPoint] = useState(null)
  const [hoveredTrade, setHoveredTrade] = useState(null)
  const clipPathId = `backtest-price-plot-${useId().replaceAll(':', '')}`
  const {
    chartContainerRef,
    getPointerPosition,
    handlePointerDown,
    handlePointerMove: handleViewportPointerMove,
    handlePointerUp,
    isDragging,
    isFullView,
    normalizedWindow,
    resetVisibleWindow,
  } = useBacktestChartViewport({
    chartWidth,
    plotLeft: chartPadding.left,
    plotWidth,
    totalPoints: points.length,
  })

  const { visiblePoints, visibleTrades } = useMemo(
    () => getVisibleBacktestChartData(points, trades, normalizedWindow),
    [normalizedWindow, points, trades],
  )

  const geometry = useMemo(() => {
    if (!visiblePoints.length) return null
    const finitePrices = visiblePoints
      .flatMap((point) => [point.close, point.swingAverage, point.ma20, point.ma60])
      .filter(Number.isFinite)
    const executionPrices = visibleTrades.map((trade) => trade.price).filter(Number.isFinite)
    const values = [...finitePrices, ...executionPrices]
    if (!values.length) return null

    const rawMinimum = Math.min(...values)
    const rawMaximum = Math.max(...values)
    const pricePadding = Math.max((rawMaximum - rawMinimum) * 0.1, Math.abs(rawMaximum) * 0.01, 0.01)
    const minimum = Math.max(0, rawMinimum - pricePadding)
    const maximum = rawMaximum + pricePadding
    const valueRange = maximum - minimum || 1
    const xScale = (index) => chartPadding.left + (index / Math.max(visiblePoints.length - 1, 1)) * plotWidth
    const yScale = (value) => chartPadding.top + ((maximum - value) / valueRange) * plotHeight
    const plotBottom = chartPadding.top + plotHeight

    return {
      xScale,
      yScale,
      yTicks: Array.from({ length: 5 }, (_, index) => maximum - (valueRange * index) / 4),
      tickIndices: getBacktestChartTickIndices(visiblePoints.length),
      plotBottom,
      closePath: createDefinedLinePath(visiblePoints.map((point) => point.close), xScale, yScale),
      swingAveragePath: createDefinedLinePath(visiblePoints.map((point) => point.swingAverage), xScale, yScale),
      ma20Path: createDefinedLinePath(visiblePoints.map((point) => point.ma20), xScale, yScale),
      ma60Path: createDefinedLinePath(visiblePoints.map((point) => point.ma60), xScale, yScale),
      tradeMarkers: layoutBacktestTradeMarkers({
        trades: visibleTrades,
        xScale,
        yScale,
        plotTop: chartPadding.top,
        plotBottom,
      }),
    }
  }, [visiblePoints, visibleTrades])

  const tradesByDate = useMemo(() => {
    const groupedTrades = new Map()
    visibleTrades.forEach((trade) => {
      groupedTrades.set(trade.executionDate, [
        ...(groupedTrades.get(trade.executionDate) ?? []),
        trade,
      ])
    })
    return groupedTrades
  }, [visibleTrades])

  useEffect(() => {
    setHoveredPoint(null)
    setHoveredTrade(null)
  }, [normalizedWindow.end, normalizedWindow.start])

  const updateHover = (index, event) => {
    const position = getPointerPosition(event)
    if (!position) return
    const progress = clamp(
      (position.chartX - chartPadding.left) / plotWidth,
      0,
      1,
    )
    setHoveredPoint({
      index,
      x: position.relativeX,
      y: clamp(position.relativeY, 78, Math.max(position.bounds.height - 78, 78)),
      alignLeft: progress > 0.68,
    })
  }

  const handlePointerMove = (event) => {
    if (handleViewportPointerMove(event)) {
      setHoveredPoint(null)
      setHoveredTrade(null)
      return
    }
    if (!geometry || !visiblePoints.length) return
    const position = getPointerPosition(event)
    if (!position) return
    const progress = clamp((position.chartX - chartPadding.left) / plotWidth, 0, 1)
    setHoveredTrade(null)
    updateHover(Math.round(progress * Math.max(visiblePoints.length - 1, 0)), event)
  }

  const handleTradeHover = (trade, event) => {
    if (isDragging) return
    event.stopPropagation()
    setHoveredTrade(trade)
    updateHover(trade.pointIndex, event)
  }

  const clearHover = () => {
    setHoveredPoint(null)
    setHoveredTrade(null)
  }

  const resetZoom = () => {
    clearHover()
    resetVisibleWindow()
  }

  const activePoint = hoveredPoint ? visiblePoints[hoveredPoint.index] : null
  const activeTrades = hoveredTrade
    ? [hoveredTrade]
    : activePoint ? tradesByDate.get(activePoint.date) ?? [] : []
  const axisDateFormatter = axisFormatters[getBacktestAxisDateDetail(visiblePoints)]
  const series = [
    ['close', 'is-close'],
    ['swingAverage', 'is-ma10'],
    ['ma20', 'is-fast-ma'],
    ['ma60', 'is-slow-ma'],
  ]

  return (
    <section className="backtest-card backtest-chart-card backtest-price-signal-card" aria-labelledby="backtest-price-signals-title">
      <div className="backtest-card-header">
        <div>
          <p>Layered strategy execution</p>
          <h2 id="backtest-price-signals-title">Price &amp; Strategy Signals</h2>
          <span>Wheel to zoom, drag to pan, and double-click to reset the historical time range.</span>
        </div>
      </div>

      <div className="backtest-price-signal-toolbar">
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
        <button type="button" onClick={resetZoom} disabled={isFullView}>Reset Zoom</button>
      </div>

      {geometry ? (
        <div
          ref={chartContainerRef}
          className={`backtest-line-chart backtest-price-signal-chart${isDragging ? ' is-dragging' : ''}`}
          data-visible-start={normalizedWindow.start}
          data-visible-end={normalizedWindow.end}
          onDoubleClick={resetZoom}
          onPointerCancel={handlePointerUp}
          onPointerDown={handlePointerDown}
          onPointerLeave={() => {
            if (!isDragging) clearHover()
          }}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
        >
          <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} preserveAspectRatio="none" role="img" aria-label={`Close, ${swingAverageType}, Core moving averages and Core and Swing trade markers`}>
            <defs>
              <clipPath id={clipPathId}>
                <rect x={chartPadding.left} y={chartPadding.top} width={plotWidth} height={plotHeight} />
              </clipPath>
            </defs>
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
                key={`price-x-${visiblePoints[index].date}`}
              >
                {formatDate(visiblePoints[index].date, axisDateFormatter)}
              </text>
            ))}
            <g clipPath={`url(#${clipPathId})`}>
              <path className="backtest-close-price-line" d={geometry.closePath} />
              <path className="backtest-ma10-line" d={geometry.swingAveragePath} />
              <path className="backtest-fast-ma-line" d={geometry.ma20Path} />
              <path className="backtest-slow-ma-line" d={geometry.ma60Path} />
              {geometry.tradeMarkers.map((marker) => (
                <TradeMarker
                  marker={marker}
                  onHover={handleTradeHover}
                  onLeave={() => setHoveredTrade(null)}
                  key={marker.id}
                />
              ))}
              {hoveredPoint && activePoint && (
                <>
                  <line className="backtest-chart-hover-line" x1={geometry.xScale(hoveredPoint.index)} x2={geometry.xScale(hoveredPoint.index)} y1={chartPadding.top} y2={geometry.plotBottom} />
                  {series.map(([key, className]) => Number.isFinite(activePoint[key]) && (
                    <circle className={`backtest-chart-hover-point ${className}`} cx={geometry.xScale(hoveredPoint.index)} cy={geometry.yScale(activePoint[key])} r="3.7" key={key} />
                  ))}
                </>
              )}
            </g>
          </svg>

          {hoveredPoint && activePoint && !isDragging && (
            <div className={`backtest-chart-tooltip backtest-price-signal-tooltip${hoveredPoint.alignLeft ? ' is-left' : ''}`} style={{ left: hoveredPoint.x, top: hoveredPoint.y }} role="tooltip">
              <strong>{formatDate(activePoint.date, tooltipDateFormatter)}</strong>
              {!hoveredTrade && (
                <>
                  <span>Close <b>{Number.isFinite(activePoint.close) ? formatCurrency(activePoint.close) : '-'}</b></span>
                  <span>{swingAverageType} <b>{Number.isFinite(activePoint.swingAverage) ? formatCurrency(activePoint.swingAverage) : '-'}</b></span>
                  <span>MA{coreFastMa} <b>{Number.isFinite(activePoint.ma20) ? formatCurrency(activePoint.ma20) : '-'}</b></span>
                  <span>MA{coreSlowMa} <b>{Number.isFinite(activePoint.ma60) ? formatCurrency(activePoint.ma60) : '-'}</b></span>
                </>
              )}
              {activeTrades.map((trade) => <TradeTooltipDetails trade={trade} key={trade.id} />)}
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
