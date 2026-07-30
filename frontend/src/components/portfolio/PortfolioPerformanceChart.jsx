import { useMemo, useState } from 'react'
import { createLinePath } from '../market-analysis/chartMath'
import {
  createPortfolioPerformanceSeries,
  portfolioPerformanceRanges,
} from '../../data/portfolioData'
import { formatCompactCurrency, formatCurrency } from './portfolioMath'

const chartWidth = 760
const chartHeight = 268
const chartPadding = { top: 18, right: 20, bottom: 38, left: 66 }

export default function PortfolioPerformanceChart({ totalAccountValue, costBasis }) {
  const [selectedRange, setSelectedRange] = useState('3M')
  const [hoveredPoint, setHoveredPoint] = useState(null)
  const series = useMemo(
    () => createPortfolioPerformanceSeries(selectedRange, totalAccountValue, costBasis),
    [costBasis, selectedRange, totalAccountValue],
  )

  const geometry = useMemo(() => {
    const allValues = [...series.totalAccountValue, ...series.costBasis]
    const rawMinimum = Math.min(...allValues)
    const rawMaximum = Math.max(...allValues)
    const padding = Math.max((rawMaximum - rawMinimum) * 0.12, rawMaximum * 0.02, 1)
    const minimum = Math.max(0, rawMinimum - padding)
    const maximum = rawMaximum + padding
    const plotWidth = chartWidth - chartPadding.left - chartPadding.right
    const plotHeight = chartHeight - chartPadding.top - chartPadding.bottom
    const valueRange = maximum - minimum || 1
    const xScale = (index) => chartPadding.left + (index / Math.max(series.totalAccountValue.length - 1, 1)) * plotWidth
    const yScale = (value) => chartPadding.top + ((maximum - value) / valueRange) * plotHeight
    const yTicks = Array.from({ length: 4 }, (_, index) => maximum - (valueRange * index) / 3)

    return {
      xScale,
      yScale,
      yTicks,
      plotBottom: chartPadding.top + plotHeight,
      totalAccountValuePath: createLinePath(series.totalAccountValue, xScale, yScale),
      costBasisPath: createLinePath(series.costBasis, xScale, yScale),
    }
  }, [series])

  const lastIndex = series.totalAccountValue.length - 1

  const handleChartPointerMove = (event) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    const plotLeft = (chartPadding.left / chartWidth) * bounds.width
    const plotRight = (chartPadding.right / chartWidth) * bounds.width
    const plotWidth = Math.max(bounds.width - plotLeft - plotRight, 1)
    const pointerX = Math.min(Math.max(event.clientX - bounds.left, plotLeft), plotLeft + plotWidth)
    const progress = (pointerX - plotLeft) / plotWidth
    const index = Math.round(progress * Math.max(series.totalAccountValue.length - 1, 0))
    const labelIndex = Math.round(progress * Math.max(series.labels.length - 1, 0))

    setHoveredPoint({
      index,
      label: series.labels[labelIndex],
      x: pointerX,
      y: Math.min(Math.max(event.clientY - bounds.top, 52), Math.max(bounds.height - 52, 52)),
      alignLeft: progress > 0.68,
    })
  }

  return (
    <section className="portfolio-card portfolio-performance-panel" aria-labelledby="portfolio-performance-title">
      <div className="portfolio-card-header portfolio-performance-header">
        <div>
          <p>Account performance</p>
          <h2 id="portfolio-performance-title">Portfolio Performance</h2>
          <span className="portfolio-performance-description">Demo Data based on displayed holdings, not historical backend performance.</span>
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
        <span><i className="is-value" aria-hidden="true" />Total Account Value <strong>{formatCurrency(totalAccountValue)}</strong></span>
        <span><i className="is-cost-basis" aria-hidden="true" />Cost Basis <strong>{formatCurrency(costBasis)}</strong></span>
      </div>

      <div
        className="portfolio-performance-chart"
        onPointerMove={handleChartPointerMove}
        onPointerLeave={() => setHoveredPoint(null)}
        onPointerCancel={() => setHoveredPoint(null)}
      >
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

          {geometry.yTicks.map((tick, index) => {
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

          {series.labels.map((label, index) => {
            const x = chartPadding.left + (index / Math.max(series.labels.length - 1, 1))
              * (chartWidth - chartPadding.left - chartPadding.right)
            return (
              <text
                className="portfolio-chart-x-label"
                x={x}
                y={chartHeight - 11}
                textAnchor={index === 0 ? 'start' : index === series.labels.length - 1 ? 'end' : 'middle'}
                key={label}
              >
                {label}
              </text>
            )
          })}

          <path
            className="portfolio-value-area"
            d={`${geometry.totalAccountValuePath} L ${geometry.xScale(lastIndex)} ${geometry.plotBottom} L ${geometry.xScale(0)} ${geometry.plotBottom} Z`}
          />
          <path className="portfolio-cost-basis-line" d={geometry.costBasisPath} />
          <path className="portfolio-value-line" d={geometry.totalAccountValuePath} />
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
                cy={geometry.yScale(series.costBasis[hoveredPoint.index])}
                r="3.5"
              />
              <circle
                className="portfolio-chart-hover-point is-account-value"
                cx={geometry.xScale(hoveredPoint.index)}
                cy={geometry.yScale(series.totalAccountValue[hoveredPoint.index])}
                r="4"
              />
            </>
          )}
          <circle
            className="portfolio-cost-basis-endpoint"
            cx={geometry.xScale(lastIndex)}
            cy={geometry.yScale(series.costBasis[lastIndex])}
            r="3.4"
          />
          <circle
            className="portfolio-value-endpoint"
            cx={geometry.xScale(lastIndex)}
            cy={geometry.yScale(series.totalAccountValue[lastIndex])}
            r="4"
          />
        </svg>
        {hoveredPoint && (
          <div
            className={`portfolio-performance-tooltip${hoveredPoint.alignLeft ? ' is-left' : ''}`}
            style={{ left: hoveredPoint.x, top: hoveredPoint.y }}
            role="tooltip"
          >
            <strong>{hoveredPoint.label}</strong>
            <span>Total Account Value <b>{formatCurrency(series.totalAccountValue[hoveredPoint.index])}</b></span>
            <span>Cost Basis <b>{formatCurrency(series.costBasis[hoveredPoint.index])}</b></span>
          </div>
        )}
      </div>
    </section>
  )
}
