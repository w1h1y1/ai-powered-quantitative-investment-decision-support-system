import { useEffect, useMemo, useRef, useState } from 'react'
import { createLinePath } from '../market-analysis/chartMath'
import { portfolioApi } from '../../services/portfolioApi'
import { formatCompactCurrency, formatCurrency } from './portfolioMath'

const chartWidth = 760
const chartHeight = 268
const chartPadding = { top: 18, right: 20, bottom: 38, left: 66 }
const portfolioPerformanceRanges = ['1M', '3M', '6M', '1Y']
const axisDateFormatter = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' })
const fullDateFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
})

function parseFiniteNumber(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function formatPointLabel(value) {
  if (!value) return ''
  const parsed = new Date(`${value}T00:00:00`)
  if (Number.isNaN(parsed.getTime())) return value
  return fullDateFormatter.format(parsed)
}

function formatAxisLabel(value) {
  if (!value) return ''
  const parsed = new Date(`${value}T00:00:00`)
  if (Number.isNaN(parsed.getTime())) return value
  return axisDateFormatter.format(parsed)
}

function buildAxisLabels(points) {
  if (!points.length) return []
  if (points.length === 1) {
    return [{ index: 0, label: formatAxisLabel(points[0].date) }]
  }

  const labelCount = Math.min(5, points.length)
  const indexes = new Set()
  for (let index = 0; index < labelCount; index += 1) {
    indexes.add(Math.round((index / (labelCount - 1)) * (points.length - 1)))
  }

  return Array.from(indexes)
    .sort((first, second) => first - second)
    .map((index) => ({
      index,
      label: formatAxisLabel(points[index].date),
    }))
}

function normalizePerformancePayload(payload) {
  const points = (Array.isArray(payload?.points) ? payload.points : [])
    .filter((point) => point && typeof point === 'object')
    .map((point) => ({
      date: point.date,
      label: formatPointLabel(point.date),
      totalAccountValue: parseFiniteNumber(point.total_account_value),
      costBasis: parseFiniteNumber(point.cost_basis),
      cash: parseFiniteNumber(point.cash),
      holdingsValue: parseFiniteNumber(point.holdings_value),
      valuationSource: point.valuation_source || '',
      isLive: Boolean(point.is_live),
    }))
    .filter((point) => (
      point.date
      && Number.isFinite(point.totalAccountValue)
      && Number.isFinite(point.costBasis)
    ))

  return {
    points,
    axisLabels: buildAxisLabels(points),
    metadata: payload?.metadata && typeof payload.metadata === 'object' ? payload.metadata : {},
  }
}

export default function PortfolioPerformanceChart({ costBasis, refreshKey, totalAccountValue }) {
  const [selectedRange, setSelectedRange] = useState('3M')
  const [hoveredPoint, setHoveredPoint] = useState(null)
  const [performancePayload, setPerformancePayload] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [requestError, setRequestError] = useState('')
  const [retryCount, setRetryCount] = useState(0)
  const requestIdRef = useRef(0)

  useEffect(() => {
    let isCurrent = true
    const requestId = requestIdRef.current + 1
    requestIdRef.current = requestId
    setIsLoading(true)
    setRequestError('')
    setHoveredPoint(null)

    portfolioApi.performance(selectedRange)
      .then((payload) => {
        if (!isCurrent || requestId !== requestIdRef.current) return
        setPerformancePayload(payload)
      })
      .catch((error) => {
        if (!isCurrent || requestId !== requestIdRef.current) return
        setRequestError(error.message || 'Unable to load portfolio performance.')
      })
      .finally(() => {
        if (!isCurrent || requestId !== requestIdRef.current) return
        setIsLoading(false)
      })

    return () => {
      isCurrent = false
    }
  }, [refreshKey, retryCount, selectedRange])

  const series = useMemo(
    () => normalizePerformancePayload(performancePayload),
    [performancePayload],
  )
  const totalAccountValueSeries = useMemo(
    () => series.points.map((point) => point.totalAccountValue),
    [series.points],
  )
  const costBasisSeries = useMemo(
    () => series.points.map((point) => point.costBasis),
    [series.points],
  )
  const hasChartData = series.points.length > 0
  const latestPoint = hasChartData ? series.points[series.points.length - 1] : null
  const legendTotalAccountValue = latestPoint?.totalAccountValue ?? totalAccountValue
  const legendCostBasis = latestPoint?.costBasis ?? costBasis

  const geometry = useMemo(() => {
    if (!series.points.length) return null

    const allValues = series.points.flatMap((point) => [point.totalAccountValue, point.costBasis])
    const rawMinimum = Math.min(...allValues)
    const rawMaximum = Math.max(...allValues)
    const padding = Math.max((rawMaximum - rawMinimum) * 0.12, rawMaximum * 0.02, 1)
    const minimum = Math.max(0, rawMinimum - padding)
    const maximum = rawMaximum + padding
    const plotWidth = chartWidth - chartPadding.left - chartPadding.right
    const plotHeight = chartHeight - chartPadding.top - chartPadding.bottom
    const valueRange = maximum - minimum || 1
    const xScale = (index) => chartPadding.left + (index / Math.max(series.points.length - 1, 1)) * plotWidth
    const yScale = (value) => chartPadding.top + ((maximum - value) / valueRange) * plotHeight
    const yTicks = Array.from({ length: 4 }, (_, index) => maximum - (valueRange * index) / 3)

    return {
      xScale,
      yScale,
      yTicks,
      plotBottom: chartPadding.top + plotHeight,
      totalAccountValuePath: createLinePath(totalAccountValueSeries, xScale, yScale),
      costBasisPath: createLinePath(costBasisSeries, xScale, yScale),
    }
  }, [costBasisSeries, series.points, totalAccountValueSeries])

  const lastIndex = series.points.length - 1
  const canDrawContinuousSeries = lastIndex > 0

  const handleChartPointerMove = (event) => {
    if (!hasChartData) return

    const bounds = event.currentTarget.getBoundingClientRect()
    const plotLeft = (chartPadding.left / chartWidth) * bounds.width
    const plotRight = (chartPadding.right / chartWidth) * bounds.width
    const plotWidth = Math.max(bounds.width - plotLeft - plotRight, 1)
    const pointerX = Math.min(Math.max(event.clientX - bounds.left, plotLeft), plotLeft + plotWidth)
    const progress = (pointerX - plotLeft) / plotWidth
    const index = Math.round(progress * Math.max(series.points.length - 1, 0))

    setHoveredPoint({
      index,
      label: series.points[index]?.label,
      x: pointerX,
      y: Math.min(Math.max(event.clientY - bounds.top, 52), Math.max(bounds.height - 52, 52)),
      alignLeft: progress > 0.68,
    })
  }

  const handleRetry = () => {
    setRetryCount((value) => value + 1)
  }

  const partialMessage = series.metadata?.is_partial
    ? `Partial data${series.metadata.missing_price_count ? `: ${series.metadata.missing_price_count} missing price point${series.metadata.missing_price_count === 1 ? '' : 's'}` : ''}.`
    : ''

  return (
    <section className="portfolio-card portfolio-performance-panel" aria-labelledby="portfolio-performance-title">
      <div className="portfolio-card-header portfolio-performance-header">
        <div>
          <p>Account performance</p>
          <h2 id="portfolio-performance-title">Portfolio Performance</h2>
          <span className="portfolio-performance-description">Transactions and market-data daily prices</span>
        </div>
        <div className="range-selector" role="radiogroup" aria-label="Portfolio performance time range">
          {portfolioPerformanceRanges.map((range) => (
            <button
              className={selectedRange === range ? 'is-active' : ''}
              type="button"
              role="radio"
              aria-checked={selectedRange === range}
              onClick={() => setSelectedRange(range)}
              key={range}
            >
              {range}
            </button>
          ))}
        </div>
      </div>

      <div className="portfolio-chart-legend" aria-label="Chart legend">
        <span><i className="is-value" aria-hidden="true" />Total Account Value <strong>{formatCurrency(legendTotalAccountValue)}</strong></span>
        <span><i className="is-cost-basis" aria-hidden="true" />Cost Basis <strong>{formatCurrency(legendCostBasis)}</strong></span>
      </div>

      {partialMessage && !isLoading && !requestError && (
        <p className="portfolio-performance-warning" role="status">{partialMessage}</p>
      )}

      <div
        className="portfolio-performance-chart"
        onPointerMove={handleChartPointerMove}
        onPointerLeave={() => setHoveredPoint(null)}
        onPointerCancel={() => setHoveredPoint(null)}
      >
        {isLoading && (
          <div className="portfolio-performance-state" role="status">
            Loading performance...
          </div>
        )}

        {!isLoading && requestError && (
          <div className="portfolio-performance-state is-error" role="alert">
            <strong>Unable to load performance.</strong>
            <span>{requestError}</span>
            <button type="button" onClick={handleRetry}>Retry</button>
          </div>
        )}

        {!isLoading && !requestError && !hasChartData && (
          <div className="portfolio-performance-state">
            <strong>No performance data available.</strong>
            <span>Only real portfolio history is shown here.</span>
          </div>
        )}

        {!isLoading && !requestError && hasChartData && geometry && (
          <svg
            viewBox={`0 0 ${chartWidth} ${chartHeight}`}
            preserveAspectRatio="none"
            role="img"
            aria-label={`${selectedRange} total account value and cost basis chart`}
          >
            <defs>
              <linearGradient id="totalAccountValueArea" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#6877f5" stopOpacity="0.18" />
                <stop offset="100%" stopColor="#6877f5" stopOpacity="0" />
              </linearGradient>
            </defs>

            {geometry.yTicks.map((tick) => {
              const y = geometry.yScale(tick)
              return (
                <g key={tick}>
                  <line
                    className="portfolio-chart-grid-line"
                    x1={chartPadding.left}
                    x2={chartWidth - chartPadding.right}
                    y1={y}
                    y2={y}
                  />
                  <text className="portfolio-chart-y-label" x={chartPadding.left - 10} y={y + 3} textAnchor="end">
                    {formatCompactCurrency(tick)}
                  </text>
                </g>
              )
            })}

            {series.axisLabels.map((axisLabel) => {
              const x = geometry.xScale(axisLabel.index)
              return (
                <text
                  className="portfolio-chart-x-label"
                  x={x}
                  y={chartHeight - 11}
                  textAnchor={axisLabel.index === 0 ? 'start' : axisLabel.index === lastIndex ? 'end' : 'middle'}
                  key={`${axisLabel.index}-${axisLabel.label}`}
                >
                  {axisLabel.label}
                </text>
              )
            })}

            {canDrawContinuousSeries && (
              <>
                <path
                  className="portfolio-value-area"
                  d={`${geometry.totalAccountValuePath} L ${geometry.xScale(lastIndex)} ${geometry.plotBottom} L ${geometry.xScale(0)} ${geometry.plotBottom} Z`}
                />
                <path className="portfolio-cost-basis-line" d={geometry.costBasisPath} />
                <path className="portfolio-value-line" d={geometry.totalAccountValuePath} />
              </>
            )}
            {hoveredPoint && (
              <>
                <line
                  className="portfolio-chart-hover-line"
                  x1={geometry.xScale(hoveredPoint.index)}
                  x2={geometry.xScale(hoveredPoint.index)}
                  y1={chartPadding.top}
                  y2={geometry.plotBottom}
                />
                <circle
                  className="portfolio-chart-hover-point is-cost-basis"
                  cx={geometry.xScale(hoveredPoint.index)}
                  cy={geometry.yScale(costBasisSeries[hoveredPoint.index])}
                  r="3.5"
                />
                <circle
                  className="portfolio-chart-hover-point is-account-value"
                  cx={geometry.xScale(hoveredPoint.index)}
                  cy={geometry.yScale(totalAccountValueSeries[hoveredPoint.index])}
                  r="4"
                />
              </>
            )}
            <circle
              className="portfolio-cost-basis-endpoint"
              cx={geometry.xScale(lastIndex)}
              cy={geometry.yScale(costBasisSeries[lastIndex])}
              r="3.4"
            />
            <circle
              className="portfolio-value-endpoint"
              cx={geometry.xScale(lastIndex)}
              cy={geometry.yScale(totalAccountValueSeries[lastIndex])}
              r="4"
            />
          </svg>
        )}

        {hoveredPoint && hasChartData && (
          <div
            className={`portfolio-performance-tooltip${hoveredPoint.alignLeft ? ' is-left' : ''}`}
            style={{ left: hoveredPoint.x, top: hoveredPoint.y }}
            role="tooltip"
          >
            <strong>{hoveredPoint.label}</strong>
            <span>Total Account Value <b>{formatCurrency(totalAccountValueSeries[hoveredPoint.index])}</b></span>
            <span>Cost Basis <b>{formatCurrency(costBasisSeries[hoveredPoint.index])}</b></span>
          </div>
        )}
      </div>
    </section>
  )
}
