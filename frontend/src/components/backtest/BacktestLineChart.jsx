import { useEffect, useMemo, useState } from 'react'
import { createLinePath } from '../market-analysis/chartMath'
import { formatCompactCurrency, formatCurrency } from '../portfolio/portfolioMath'
import {
  getBacktestAxisDateDetail,
  getBacktestChartTickIndices,
  getVisibleBacktestPoints,
} from './backtestPriceSignalChartModel'
import useBacktestChartViewport from './useBacktestChartViewport'

const chartWidth = 900
const equityChartHeight = 270
const drawdownChartHeight = 210

const axisFormatters = {
  day: new Intl.DateTimeFormat('en-US', { day: '2-digit', month: 'short', timeZone: 'UTC' }),
  'month-day': new Intl.DateTimeFormat('en-US', { day: 'numeric', month: 'short', timeZone: 'UTC' }),
  'month-year': new Intl.DateTimeFormat('en-US', { month: 'short', year: '2-digit', timeZone: 'UTC' }),
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

export default function BacktestLineChart({ variant, points = [] }) {
  const [hoveredPoint, setHoveredPoint] = useState(null)
  const isDrawdown = variant === 'drawdown'
  const chartHeight = isDrawdown ? drawdownChartHeight : equityChartHeight
  const chartPadding = { top: 18, right: 20, bottom: 38, left: isDrawdown ? 62 : 76 }
  const plotWidth = chartWidth - chartPadding.left - chartPadding.right
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
  const { visiblePoints } = useMemo(
    () => getVisibleBacktestPoints(points, normalizedWindow),
    [normalizedWindow, points],
  )

  const geometry = useMemo(() => {
    if (!visiblePoints.length) return null
    const values = isDrawdown
      ? visiblePoints.map((point) => point.drawdown)
      : visiblePoints.map((point) => point.portfolioValue)
    const rawMinimum = Math.min(...values)
    const rawMaximum = Math.max(...values)
    const minimum = isDrawdown
      ? Math.min(-1, rawMinimum) * 1.12
      : Math.max(0, rawMinimum - Math.max((rawMaximum - rawMinimum) * 0.12, rawMaximum * 0.015, 1))
    const maximum = isDrawdown
      ? 0
      : rawMaximum + Math.max((rawMaximum - rawMinimum) * 0.12, rawMaximum * 0.015, 1)
    const plotHeight = chartHeight - chartPadding.top - chartPadding.bottom
    const valueRange = maximum - minimum || 1
    const xScale = (index) => chartPadding.left + (index / Math.max(visiblePoints.length - 1, 1)) * plotWidth
    const yScale = (value) => chartPadding.top + ((maximum - value) / valueRange) * plotHeight
    const yTicks = Array.from({ length: 4 }, (_, index) => maximum - (valueRange * index) / 3)

    return {
      xScale,
      yScale,
      yTicks,
      plotBottom: chartPadding.top + plotHeight,
      tickIndices: getBacktestChartTickIndices(visiblePoints.length),
      portfolioPath: isDrawdown ? '' : createLinePath(visiblePoints.map((point) => point.portfolioValue), xScale, yScale),
      drawdownPath: isDrawdown ? createLinePath(visiblePoints.map((point) => point.drawdown), xScale, yScale) : '',
    }
  }, [chartHeight, chartPadding.bottom, chartPadding.left, chartPadding.top, isDrawdown, plotWidth, visiblePoints])

  useEffect(() => {
    setHoveredPoint(null)
  }, [normalizedWindow.end, normalizedWindow.start])

  const handlePointerMove = (event) => {
    if (handleViewportPointerMove(event)) {
      setHoveredPoint(null)
      return
    }
    if (!geometry || !visiblePoints.length) return
    const position = getPointerPosition(event)
    if (!position) return
    const progress = clamp((position.chartX - chartPadding.left) / plotWidth, 0, 1)

    setHoveredPoint({
      index: Math.round(progress * Math.max(visiblePoints.length - 1, 0)),
      x: position.relativeX,
      y: clamp(position.relativeY, 54, Math.max(position.bounds.height - 54, 54)),
      alignLeft: progress > 0.68,
    })
  }

  const resetZoom = () => {
    setHoveredPoint(null)
    resetVisibleWindow()
  }

  const activePoint = hoveredPoint ? visiblePoints[hoveredPoint.index] : null
  const lastIndex = visiblePoints.length - 1
  const baselineY = geometry ? (isDrawdown ? geometry.yScale(0) : geometry.plotBottom) : 0
  const axisDateFormatter = axisFormatters[getBacktestAxisDateDetail(visiblePoints)]

  return (
    <section
      className={`backtest-card backtest-chart-card is-${variant}`}
      aria-labelledby={`backtest-${variant}-title`}
    >
      <div className="backtest-card-header">
        <div>
          <p>{isDrawdown ? 'Risk profile' : 'Performance comparison'}</p>
          <h2 id={`backtest-${variant}-title`}>{isDrawdown ? 'Drawdown' : 'Equity Curve'}</h2>
          <span>
            {isDrawdown
              ? 'Wheel to zoom, drag to pan, and double-click to reset the daily drawdown timeline.'
              : 'Wheel to zoom, drag to pan, and double-click to reset the daily marked-equity timeline.'}
          </span>
        </div>
      </div>

      <div className="backtest-chart-toolbar">
        <div className="backtest-chart-legend" aria-label={`${isDrawdown ? 'Drawdown' : 'Equity curve'} legend`}>
          {isDrawdown ? (
            <span><i className="is-drawdown" aria-hidden="true" />Drawdown</span>
          ) : (
            <span><i className="is-portfolio" aria-hidden="true" />Strategy equity</span>
          )}
        </div>
        <button type="button" onClick={resetZoom} disabled={isFullView}>Reset Zoom</button>
      </div>

      {geometry && (
        <div
          ref={chartContainerRef}
          className={`backtest-line-chart backtest-interactive-chart${isDragging ? ' is-dragging' : ''}`}
          data-visible-start={normalizedWindow.start}
          data-visible-end={normalizedWindow.end}
          onDoubleClick={resetZoom}
          onPointerCancel={handlePointerUp}
          onPointerDown={handlePointerDown}
          onPointerLeave={() => {
            if (!isDragging) setHoveredPoint(null)
          }}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
        >
          <svg
            viewBox={`0 0 ${chartWidth} ${chartHeight}`}
            preserveAspectRatio="none"
            role="img"
            aria-label={isDrawdown ? 'Strategy drawdown chart' : 'Strategy equity curve chart'}
          >
            <defs>
              <linearGradient id={`backtest-${variant}-area`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={isDrawdown ? '#ef6a78' : '#6877f5'} stopOpacity={isDrawdown ? '0.20' : '0.16'} />
                <stop offset="100%" stopColor={isDrawdown ? '#ef6a78' : '#6877f5'} stopOpacity="0" />
              </linearGradient>
            </defs>

            {geometry.yTicks.map((tick, index) => {
              const y = geometry.yScale(tick)
              return (
                <g key={`y-${index}`}>
                  <line
                    className="backtest-chart-grid-line"
                    x1={chartPadding.left}
                    x2={chartWidth - chartPadding.right}
                    y1={y}
                    y2={y}
                  />
                  <text
                    className="backtest-chart-axis-label"
                    x={chartPadding.left - 10}
                    y={y + 3}
                    textAnchor="end"
                  >
                    {isDrawdown ? `${tick.toFixed(1)}%` : formatCompactCurrency(tick)}
                  </text>
                </g>
              )
            })}

            {geometry.tickIndices.map((index, tickPosition) => (
              <text
                className="backtest-chart-axis-label"
                x={geometry.xScale(index)}
                y={chartHeight - 11}
                textAnchor={tickPosition === 0 ? 'start' : tickPosition === geometry.tickIndices.length - 1 ? 'end' : 'middle'}
                key={`x-${visiblePoints[index].date}`}
              >
                {formatDate(visiblePoints[index].date, axisDateFormatter)}
              </text>
            ))}

            <path
              className={`backtest-chart-area is-${variant}`}
              style={{ fill: `url(#backtest-${variant}-area)` }}
              d={`${isDrawdown ? geometry.drawdownPath : geometry.portfolioPath} L ${geometry.xScale(lastIndex)} ${baselineY} L ${geometry.xScale(0)} ${baselineY} Z`}
            />

            {isDrawdown ? (
              <path className="backtest-drawdown-line" d={geometry.drawdownPath} />
            ) : (
              <path className="backtest-portfolio-line" d={geometry.portfolioPath} />
            )}

            {hoveredPoint && activePoint && (
              <>
                <line
                  className="backtest-chart-hover-line"
                  x1={geometry.xScale(hoveredPoint.index)}
                  x2={geometry.xScale(hoveredPoint.index)}
                  y1={chartPadding.top}
                  y2={geometry.plotBottom}
                />
                {isDrawdown ? (
                  <circle
                    className="backtest-chart-hover-point is-drawdown"
                    cx={geometry.xScale(hoveredPoint.index)}
                    cy={geometry.yScale(activePoint.drawdown)}
                    r="4"
                  />
                ) : (
                  <circle
                    className="backtest-chart-hover-point is-portfolio"
                    cx={geometry.xScale(hoveredPoint.index)}
                    cy={geometry.yScale(activePoint.portfolioValue)}
                    r="4"
                  />
                )}
              </>
            )}
          </svg>

          {hoveredPoint && activePoint && (
            <div
              className={`backtest-chart-tooltip${hoveredPoint.alignLeft ? ' is-left' : ''}`}
              style={{ left: hoveredPoint.x, top: hoveredPoint.y }}
              role="tooltip"
            >
              <strong>{formatDate(activePoint.date, tooltipDateFormatter)}</strong>
              {isDrawdown ? (
                <span>Drawdown <b>{activePoint.drawdown.toFixed(2)}%</b></span>
              ) : (
                <span>Strategy equity <b>{formatCurrency(activePoint.portfolioValue)}</b></span>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
