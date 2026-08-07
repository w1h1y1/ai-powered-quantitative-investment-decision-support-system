import { useMemo, useState } from 'react'
import { createDefinedLinePath } from '../market-analysis/chartMath'

const chartWidth = 900
const chartHeight = 230
const chartPadding = { top: 18, right: 22, bottom: 36, left: 54 }

const axisDateFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  year: '2-digit',
  timeZone: 'UTC',
})

function formatDate(value) {
  return axisDateFormatter.format(new Date(`${value}T00:00:00Z`))
}

function getTickIndices(pointCount) {
  const lastIndex = Math.max(pointCount - 1, 0)
  return [...new Set(Array.from({ length: 5 }, (_, index) => Math.round((lastIndex * index) / 4)))]
}

export default function BacktestExposureChart({ points = [] }) {
  const [hoveredPoint, setHoveredPoint] = useState(null)
  const geometry = useMemo(() => {
    if (!points.length) return null
    const plotWidth = chartWidth - chartPadding.left - chartPadding.right
    const plotHeight = chartHeight - chartPadding.top - chartPadding.bottom
    const xScale = (index) => chartPadding.left + (index / Math.max(points.length - 1, 1)) * plotWidth
    const yScale = (value) => chartPadding.top + ((100 - value) / 100) * plotHeight
    const regimeBands = []
    let start = 0
    points.forEach((point, index) => {
      const nextRegime = points[index + 1]?.marketRegime
      if (index === points.length - 1 || nextRegime !== point.marketRegime) {
        const halfStep = (plotWidth / Math.max(points.length - 1, 1)) / 2
        const left = Math.max(chartPadding.left, xScale(start) - halfStep)
        const right = Math.min(chartWidth - chartPadding.right, xScale(index) + halfStep)
        regimeBands.push({ regime: point.marketRegime, left, width: Math.max(right - left, 1) })
        start = index + 1
      }
    })
    return {
      xScale,
      yScale,
      plotBottom: chartPadding.top + plotHeight,
      tickIndices: getTickIndices(points.length),
      yTicks: [0, 25, 50, 75, 100],
      regimeBands,
      corePath: createDefinedLinePath(points.map((point) => point.coreExposure), xScale, yScale),
      swingPath: createDefinedLinePath(points.map((point) => point.swingExposure), xScale, yScale),
      totalPath: createDefinedLinePath(points.map((point) => point.totalExposure), xScale, yScale),
    }
  }, [points])

  const handlePointerMove = (event) => {
    if (!geometry) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const plotLeft = (chartPadding.left / chartWidth) * bounds.width
    const plotRight = (chartPadding.right / chartWidth) * bounds.width
    const plotWidth = Math.max(bounds.width - plotLeft - plotRight, 1)
    const pointerX = Math.min(Math.max(event.clientX - bounds.left, plotLeft), plotLeft + plotWidth)
    const progress = (pointerX - plotLeft) / plotWidth
    setHoveredPoint({
      index: Math.round(progress * Math.max(points.length - 1, 0)),
      x: pointerX,
      y: Math.min(Math.max(event.clientY - bounds.top, 58), Math.max(bounds.height - 58, 58)),
      alignLeft: progress > 0.7,
    })
  }

  const activePoint = hoveredPoint ? points[hoveredPoint.index] : null

  return (
    <section className="backtest-card backtest-chart-card backtest-exposure-card" aria-labelledby="backtest-exposure-title">
      <div className="backtest-card-header">
        <div>
          <p>Capital deployment</p>
          <h2 id="backtest-exposure-title">Position Exposure</h2>
          <span>Independent Core and Swing exposure with the contemporaneous benchmark regime.</span>
        </div>
      </div>
      <div className="backtest-chart-legend" aria-label="Position exposure legend">
        <span><i className="is-core-exposure" aria-hidden="true" />Core Exposure</span>
        <span><i className="is-swing-exposure" aria-hidden="true" />Swing Exposure</span>
        <span><i className="is-total-exposure" aria-hidden="true" />Total Exposure</span>
        <span><i className="is-regime-bull" aria-hidden="true" />Bull</span>
        <span><i className="is-regime-neutral" aria-hidden="true" />Neutral</span>
        <span><i className="is-regime-bear" aria-hidden="true" />Bear</span>
      </div>
      {geometry && (
        <div className="backtest-line-chart backtest-exposure-chart" onPointerMove={handlePointerMove} onPointerLeave={() => setHoveredPoint(null)}>
          <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} preserveAspectRatio="none" role="img" aria-label="Core, Swing and total exposure by market regime">
            {geometry.regimeBands.map((band, index) => (
              <rect className={`backtest-regime-band is-${band.regime.toLowerCase()}`} x={band.left} y={chartPadding.top} width={band.width} height={geometry.plotBottom - chartPadding.top} key={`${band.regime}-${index}`} />
            ))}
            {geometry.yTicks.map((tick) => (
              <g key={tick}>
                <line className="backtest-chart-grid-line" x1={chartPadding.left} x2={chartWidth - chartPadding.right} y1={geometry.yScale(tick)} y2={geometry.yScale(tick)} />
                <text className="backtest-chart-axis-label" x={chartPadding.left - 9} y={geometry.yScale(tick) + 3} textAnchor="end">{tick}%</text>
              </g>
            ))}
            {geometry.tickIndices.map((index, position) => (
              <text className="backtest-chart-axis-label" x={geometry.xScale(index)} y={chartHeight - 10} textAnchor={position === 0 ? 'start' : position === geometry.tickIndices.length - 1 ? 'end' : 'middle'} key={points[index].date}>
                {formatDate(points[index].date)}
              </text>
            ))}
            <path className="backtest-core-exposure-line" d={geometry.corePath} />
            <path className="backtest-swing-exposure-line" d={geometry.swingPath} />
            <path className="backtest-total-exposure-line" d={geometry.totalPath} />
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
