import { useMemo, useState } from 'react'

const chartWidth = 960
const chartHeight = 300
const padding = { top: 24, right: 28, bottom: 42, left: 66 }

const axisDateFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
})

const tooltipDateFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
  timeZone: 'UTC',
})

function formatDate(value, formatter) {
  return formatter.format(new Date(`${value}T00:00:00Z`))
}

function formatCurrency(value) {
  return `$${value.toFixed(2)}`
}

function createPath(points, xScale, yScale, valueKey, indexOffset = 0) {
  return points.map((point, index) => (
    `${index === 0 ? 'M' : 'L'} ${xScale(index + indexOffset)} ${yScale(point[valueKey])}`
  )).join(' ')
}

function getTickIndices(pointCount, tickCount = 6) {
  const lastIndex = Math.max(pointCount - 1, 0)
  return [...new Set(Array.from({ length: tickCount }, (_, index) => Math.round((lastIndex * index) / (tickCount - 1))))]
}

export default function ForecastChart({ forecast }) {
  const [hoveredPoint, setHoveredPoint] = useState(null)
  const { historical, forecast: forecastPoints } = forecast.forecastSeries

  const geometry = useMemo(() => {
    const forecastOffset = historical.length - 1
    const combinedPointCount = historical.length + forecastPoints.length - 1
    const values = [
      ...historical.map((point) => point.price),
      ...forecastPoints.flatMap((point) => [point.lowerBound, point.upperBound]),
    ]
    const rawMinimum = Math.min(...values)
    const rawMaximum = Math.max(...values)
    const valuePadding = Math.max((rawMaximum - rawMinimum) * 0.12, rawMaximum * 0.01)
    const minimum = rawMinimum - valuePadding
    const maximum = rawMaximum + valuePadding
    const plotWidth = chartWidth - padding.left - padding.right
    const plotHeight = chartHeight - padding.top - padding.bottom
    const xScale = (index) => padding.left + (index / Math.max(combinedPointCount - 1, 1)) * plotWidth
    const yScale = (value) => padding.top + ((maximum - value) / Math.max(maximum - minimum, 1)) * plotHeight
    const yTicks = Array.from({ length: 5 }, (_, index) => maximum - ((maximum - minimum) * index) / 4)
    const historicalPath = createPath(historical, xScale, yScale, 'price')
    const forecastPath = createPath(forecastPoints, xScale, yScale, 'expectedPrice', forecastOffset)
    const upperPath = createPath(forecastPoints, xScale, yScale, 'upperBound', forecastOffset)
    const lowerReversePath = [...forecastPoints].reverse().map((point, reverseIndex) => {
      const originalIndex = forecastPoints.length - reverseIndex - 1
      return `L ${xScale(originalIndex + forecastOffset)} ${yScale(point.lowerBound)}`
    }).join(' ')
    const rangePath = `${upperPath} ${lowerReversePath} Z`
    const timeline = [
      ...historical,
      ...forecastPoints.slice(1),
    ]

    return {
      combinedPointCount,
      forecastOffset,
      historicalPath,
      forecastPath,
      rangePath,
      timeline,
      xScale,
      yScale,
      yTicks,
      tickIndices: getTickIndices(combinedPointCount),
      plotBottom: padding.top + plotHeight,
    }
  }, [forecastPoints, historical])

  const handlePointerMove = (event) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    const plotLeft = (padding.left / chartWidth) * bounds.width
    const plotRight = (padding.right / chartWidth) * bounds.width
    const plotWidth = Math.max(bounds.width - plotLeft - plotRight, 1)
    const pointerX = Math.min(Math.max(event.clientX - bounds.left, plotLeft), plotLeft + plotWidth)
    const progress = (pointerX - plotLeft) / plotWidth

    setHoveredPoint({
      index: Math.round(progress * Math.max(geometry.combinedPointCount - 1, 0)),
      x: pointerX,
      y: Math.min(Math.max(event.clientY - bounds.top, 66), Math.max(bounds.height - 66, 66)),
      alignLeft: progress > 0.72,
    })
  }

  const activeTimelinePoint = hoveredPoint ? geometry.timeline[hoveredPoint.index] : null
  const isForecastPoint = hoveredPoint?.index >= geometry.forecastOffset
  const activeForecastPoint = isForecastPoint
    ? forecastPoints[hoveredPoint.index - geometry.forecastOffset]
    : null

  return (
    <section className="prediction-card prediction-chart-card" aria-labelledby="prediction-chart-title">
      <div className="prediction-card-header">
        <div>
          <p>Historical and simulated path</p>
          <h2 id="prediction-chart-title">Forecast Chart</h2>
          <span>Forecast values begin at the marked boundary and are not observed market prices.</span>
        </div>
      </div>

      <div className="prediction-chart-legend" aria-label="Forecast chart legend">
        <span><i className="is-historical" aria-hidden="true" />Historical Price</span>
        <span><i className="is-forecast" aria-hidden="true" />Forecast</span>
        <span><i className="is-range" aria-hidden="true" />Forecast Range</span>
      </div>

      <div
        className="prediction-line-chart"
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setHoveredPoint(null)}
        onPointerCancel={() => setHoveredPoint(null)}
      >
        <svg
          viewBox={`0 0 ${chartWidth} ${chartHeight}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={`${forecast.asset.symbol} historical price and rule-based forecast chart`}
        >
          <defs>
            <linearGradient id="prediction-forecast-range" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#6877f5" stopOpacity="0.2" />
              <stop offset="100%" stopColor="#6877f5" stopOpacity="0.05" />
            </linearGradient>
          </defs>

          {geometry.yTicks.map((tick, index) => {
            const y = geometry.yScale(tick)
            return (
              <g key={`y-${index}`}>
                <line className="prediction-chart-grid-line" x1={padding.left} x2={chartWidth - padding.right} y1={y} y2={y} />
                <text className="prediction-chart-axis-label" x={padding.left - 10} y={y + 3} textAnchor="end">
                  ${tick.toFixed(0)}
                </text>
              </g>
            )
          })}

          {geometry.tickIndices.map((index, tickPosition) => (
            <text
              className="prediction-chart-axis-label"
              x={geometry.xScale(index)}
              y={chartHeight - 12}
              textAnchor={tickPosition === 0 ? 'start' : tickPosition === geometry.tickIndices.length - 1 ? 'end' : 'middle'}
              key={`x-${geometry.timeline[index].date}`}
            >
              {formatDate(geometry.timeline[index].date, axisDateFormatter)}
            </text>
          ))}

          <path className="prediction-range-area" d={geometry.rangePath} />
          <path className="prediction-historical-line" d={geometry.historicalPath} />
          <path className="prediction-forecast-line" d={geometry.forecastPath} />

          <line
            className="prediction-start-line"
            x1={geometry.xScale(geometry.forecastOffset)}
            x2={geometry.xScale(geometry.forecastOffset)}
            y1={padding.top}
            y2={geometry.plotBottom}
          />
          <text
            className="prediction-start-label"
            x={geometry.xScale(geometry.forecastOffset) + 7}
            y={padding.top + 12}
          >
            Forecast starts
          </text>

          {hoveredPoint && activeTimelinePoint && (
            <line
              className="prediction-hover-line"
              x1={geometry.xScale(hoveredPoint.index)}
              x2={geometry.xScale(hoveredPoint.index)}
              y1={padding.top}
              y2={geometry.plotBottom}
            />
          )}
        </svg>

        {hoveredPoint && activeTimelinePoint && (
          <div
            className={`prediction-chart-tooltip${hoveredPoint.alignLeft ? ' is-left' : ''}`}
            style={{ left: hoveredPoint.x, top: hoveredPoint.y }}
            role="tooltip"
          >
            <strong>{formatDate(activeTimelinePoint.date, tooltipDateFormatter)}</strong>
            {activeForecastPoint ? (
              <>
                <span>Forecast <b>{formatCurrency(activeForecastPoint.expectedPrice)}</b></span>
                <span>Lower Bound <b>{formatCurrency(activeForecastPoint.lowerBound)}</b></span>
                <span>Upper Bound <b>{formatCurrency(activeForecastPoint.upperBound)}</b></span>
              </>
            ) : (
              <span>Historical Price <b>{formatCurrency(activeTimelinePoint.price)}</b></span>
            )}
          </div>
        )}
      </div>
    </section>
  )
}

