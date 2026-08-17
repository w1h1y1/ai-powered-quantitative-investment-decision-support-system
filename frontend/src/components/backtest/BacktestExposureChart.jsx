import { useEffect, useMemo, useState } from 'react'
import { createDefinedLinePath } from '../market-analysis/chartMath'
import {
  getBacktestAxisDateDetail,
  getBacktestChartTickIndices,
  getVisibleBacktestPoints,
} from './backtestPriceSignalChartModel'
import useBacktestChartViewport from './useBacktestChartViewport'

const chartWidth = 900
const chartHeight = 230
const chartPadding = { top: 18, right: 22, bottom: 36, left: 54 }
const plotWidth = chartWidth - chartPadding.left - chartPadding.right

const axisFormatters = {
  day: new Intl.DateTimeFormat('en-US', { day: '2-digit', month: 'short', timeZone: 'UTC' }),
  'month-day': new Intl.DateTimeFormat('en-US', { day: 'numeric', month: 'short', timeZone: 'UTC' }),
  'month-year': new Intl.DateTimeFormat('en-US', { month: 'short', year: '2-digit', timeZone: 'UTC' }),
}

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum)
}

function formatDate(value, formatter) {
  return formatter.format(new Date(`${value}T00:00:00Z`))
}

function createDefinedAreaPath(values, xScale, yScale, baselineY) {
  const paths = []
  let segment = []

  const closeSegment = () => {
    if (!segment.length) return
    const firstIndex = segment[0].index
    const lastIndex = segment[segment.length - 1].index
    paths.push([
      `M ${xScale(firstIndex)} ${baselineY}`,
      ...segment.map(({ value, index }) => `L ${xScale(index)} ${yScale(value)}`),
      `L ${xScale(lastIndex)} ${baselineY}`,
      'Z',
    ].join(' '))
    segment = []
  }

  values.forEach((value, index) => {
    if (Number.isFinite(value)) {
      segment.push({ value, index })
    } else {
      closeSegment()
    }
  })
  closeSegment()

  return paths.join(' ')
}

export default function BacktestExposureChart({ points = [] }) {
  const [hoveredPoint, setHoveredPoint] = useState(null)
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
    const plotHeight = chartHeight - chartPadding.top - chartPadding.bottom
    const xScale = (index) => chartPadding.left + (index / Math.max(visiblePoints.length - 1, 1)) * plotWidth
    const yScale = (value) => chartPadding.top + ((100 - value) / 100) * plotHeight
    const regimeBands = []
    let start = 0
    visiblePoints.forEach((point, index) => {
      const nextRegime = visiblePoints[index + 1]?.marketRegime
      if (index === visiblePoints.length - 1 || nextRegime !== point.marketRegime) {
        const halfStep = (plotWidth / Math.max(visiblePoints.length - 1, 1)) / 2
        const left = Math.max(chartPadding.left, xScale(start) - halfStep)
        const right = Math.min(chartWidth - chartPadding.right, xScale(index) + halfStep)
        regimeBands.push({
          regime: point.marketRegime || 'NEUTRAL',
          left,
          width: Math.max(right - left, 1),
        })
        start = index + 1
      }
    })
    return {
      xScale,
      yScale,
      plotBottom: chartPadding.top + plotHeight,
      tickIndices: getBacktestChartTickIndices(visiblePoints.length),
      yTicks: [0, 25, 50, 75, 100],
      regimeBands,
      coreAreaPath: createDefinedAreaPath(
        visiblePoints.map((point) => point.coreExposure),
        xScale,
        yScale,
        chartPadding.top + plotHeight,
      ),
      swingPath: createDefinedLinePath(visiblePoints.map((point) => point.swingExposure), xScale, yScale),
      totalPath: createDefinedLinePath(visiblePoints.map((point) => point.totalExposure), xScale, yScale),
    }
  }, [visiblePoints])

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
      y: clamp(position.relativeY, 58, Math.max(position.bounds.height - 58, 58)),
      alignLeft: progress > 0.7,
    })
  }

  const resetZoom = () => {
    setHoveredPoint(null)
    resetVisibleWindow()
  }

  const activePoint = hoveredPoint ? visiblePoints[hoveredPoint.index] : null
  const axisDateFormatter = axisFormatters[getBacktestAxisDateDetail(visiblePoints)]

  return (
    <section className="backtest-card backtest-chart-card backtest-exposure-card" aria-labelledby="backtest-exposure-title">
      <div className="backtest-card-header">
        <div>
          <p>Capital deployment</p>
          <h2 id="backtest-exposure-title">Position Exposure</h2>
          <span>Wheel to zoom, drag to pan, and double-click to reset the daily position timeline.</span>
        </div>
      </div>
      <div className="backtest-chart-toolbar">
        <div className="backtest-chart-legend" aria-label="Position exposure legend">
          <span><i className="is-core-exposure" aria-hidden="true" />Core Exposure</span>
          <span><i className="is-swing-exposure" aria-hidden="true" />Swing Exposure</span>
          <span><i className="is-total-exposure" aria-hidden="true" />Total Exposure</span>
          <span><i className="is-regime-bull" aria-hidden="true" />Bull</span>
          <span><i className="is-regime-neutral" aria-hidden="true" />Neutral</span>
          <span><i className="is-regime-bear" aria-hidden="true" />Bear</span>
        </div>
        <button type="button" onClick={resetZoom} disabled={isFullView}>Reset Zoom</button>
      </div>
      {geometry && (
        <div
          ref={chartContainerRef}
          className={`backtest-line-chart backtest-exposure-chart backtest-interactive-chart${isDragging ? ' is-dragging' : ''}`}
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
          <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} preserveAspectRatio="none" role="img" aria-label="Core, Swing and total exposure by market regime">
            {geometry.regimeBands.map((band, index) => (
              <rect className={`backtest-regime-band is-${band.regime.toLowerCase()}`} x={band.left} y={chartPadding.top} width={band.width} height={geometry.plotBottom - chartPadding.top} key={`${band.regime}-${band.left}-${index}`} />
            ))}
            <path className="backtest-core-exposure-area" d={geometry.coreAreaPath} />
            {geometry.yTicks.map((tick) => (
              <g key={tick}>
                <line className="backtest-chart-grid-line" x1={chartPadding.left} x2={chartWidth - chartPadding.right} y1={geometry.yScale(tick)} y2={geometry.yScale(tick)} />
                <text className="backtest-chart-axis-label" x={chartPadding.left - 9} y={geometry.yScale(tick) + 3} textAnchor="end">{tick}%</text>
              </g>
            ))}
            {geometry.tickIndices.map((index, position) => (
              <text className="backtest-chart-axis-label" x={geometry.xScale(index)} y={chartHeight - 10} textAnchor={position === 0 ? 'start' : position === geometry.tickIndices.length - 1 ? 'end' : 'middle'} key={visiblePoints[index].date}>
                {formatDate(visiblePoints[index].date, axisDateFormatter)}
              </text>
            ))}
            <path className="backtest-total-exposure-line" d={geometry.totalPath} />
            <path className="backtest-swing-exposure-line" d={geometry.swingPath} />
            {hoveredPoint && activePoint && (
              <line className="backtest-chart-hover-line" x1={geometry.xScale(hoveredPoint.index)} x2={geometry.xScale(hoveredPoint.index)} y1={chartPadding.top} y2={geometry.plotBottom} />
            )}
          </svg>
          {hoveredPoint && activePoint && (
            <div className={`backtest-chart-tooltip${hoveredPoint.alignLeft ? ' is-left' : ''}`} style={{ left: hoveredPoint.x, top: hoveredPoint.y }} role="tooltip">
              <strong>{activePoint.date}</strong>
              <span>Market Regime <b>{activePoint.marketRegime}</b></span>
              <span>Core Exposure <b>{activePoint.coreExposure.toFixed(2)}%</b></span>
              <span>Swing Exposure <b>{activePoint.swingExposure.toFixed(2)}%</b></span>
              <span>Total Exposure <b>{activePoint.totalExposure.toFixed(2)}%</b></span>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
