import { useMemo, useState } from 'react'
import {
  formatDashboardCandleTooltip,
  isCustomMarketDataRange,
} from './dashboardSecurityModel'

const chartWidth = 720
const chartHeight = 330
const padding = { top: 18, right: 24, bottom: 32, left: 56 }
const pricePlotHeight = 205
const volumeGap = 24
const volumePlotHeight = 52
const tooltipWidth = 218
const tooltipHeight = 180

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum)
}

function formatCompactVolume(value) {
  if (!Number.isFinite(value)) return '0'
  return new Intl.NumberFormat('en-US', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

function createChartGeometry(candles) {
  const highs = candles.map((candle) => candle.high)
  const lows = candles.map((candle) => candle.low)
  const rawMinimum = Math.min(...lows)
  const rawMaximum = Math.max(...highs)
  const buffer = Math.max((rawMaximum - rawMinimum) * 0.12, 0.01)
  const minimum = rawMinimum - buffer
  const maximum = rawMaximum + buffer
  const plotWidth = chartWidth - padding.left - padding.right
  const priceBottom = padding.top + pricePlotHeight
  const volumeTop = priceBottom + volumeGap
  const volumeMaximum = Math.max(...candles.map((candle) => candle.volume), 1)
  const candleStep = candles.length > 1 ? plotWidth / (candles.length - 1) : plotWidth
  const candleWidth = Math.max(3, Math.min(9, candleStep * 0.56))

  const scalePrice = (value) => padding.top + ((maximum - value) / (maximum - minimum)) * pricePlotHeight
  const scaleVolume = (value) => (value / volumeMaximum) * volumePlotHeight
  const items = candles.map((candle, index) => {
    const x = candles.length > 1
      ? padding.left + (index / (candles.length - 1)) * plotWidth
      : padding.left + plotWidth / 2
    const openY = scalePrice(candle.open)
    const closeY = scalePrice(candle.close)
    const highY = scalePrice(candle.high)
    const lowY = scalePrice(candle.low)
    const isUp = candle.close >= candle.open
    const bodyTop = Math.min(openY, closeY)
    const bodyHeight = Math.max(Math.abs(openY - closeY), 1)
    const volumeHeight = Math.max(scaleVolume(candle.volume), 1)

    return {
      ...candle,
      x,
      openY,
      closeY,
      highY,
      lowY,
      isUp,
      bodyTop,
      bodyHeight,
      volumeHeight,
      volumeY: volumeTop + volumePlotHeight - volumeHeight,
    }
  })

  const gridValues = Array.from({ length: 5 }, (_, index) => maximum - ((maximum - minimum) / 4) * index)
  const labelStep = Math.max(1, Math.floor(candles.length / 4))
  const labelIndexes = Array.from(new Set([
    0,
    ...candles.map((_, index) => index).filter((index) => index % labelStep === 0),
    candles.length - 1,
  ])).filter((index) => index >= 0 && index < candles.length)

  return {
    candleWidth,
    gridValues,
    items,
    labelIndexes,
    plotWidth,
    priceBottom,
    volumeMaximum,
    volumeTop,
  }
}

function ChartState({ children }) {
  return (
    <div className="price-chart-state" role="status">
      {children}
    </div>
  )
}

export default function PriceChart({
  chart,
  customRange,
  customRangeError,
  customRangeMaxDate,
  onCustomRangeApply,
  onCustomRangeChange,
  onRangeChange,
  selectedRange,
}) {
  const activeRange = chart.ranges.includes(selectedRange) ? selectedRange : chart.ranges[0]
  const candles = chart.candles ?? []
  const hasCandles = candles.length > 0
  const [hoverState, setHoverState] = useState(null)
  const geometry = useMemo(
    () => (hasCandles ? createChartGeometry(candles) : null),
    [candles, hasCandles],
  )
  const hoveredItem = hoverState && geometry ? geometry.items[hoverState.index] : null
  const tooltip = hoveredItem ? formatDashboardCandleTooltip(hoveredItem, chart.currency) : null

  const handlePointerMove = (event) => {
    if (!geometry?.items.length) return

    const bounds = event.currentTarget.getBoundingClientRect()
    if (!bounds.width || !bounds.height) return

    const relativeX = event.clientX - bounds.left
    const relativeY = event.clientY - bounds.top
    const chartX = (relativeX / bounds.width) * chartWidth
    const rawIndex = geometry.items.length > 1
      ? Math.round(((chartX - padding.left) / geometry.plotWidth) * (geometry.items.length - 1))
      : 0
    const index = clamp(rawIndex, 0, geometry.items.length - 1)
    const tooltipLeft = clamp(relativeX + 14, 8, Math.max(8, bounds.width - tooltipWidth - 8))
    const tooltipTopCandidate = relativeY > tooltipHeight + 28
      ? relativeY - tooltipHeight - 14
      : relativeY + 14
    const tooltipTop = clamp(tooltipTopCandidate, 8, Math.max(8, bounds.height - tooltipHeight - 8))

    setHoverState({
      index,
      tooltipLeft,
      tooltipTop,
    })
  }

  return (
    <section className="dashboard-panel price-chart-panel" aria-labelledby="price-chart-title">
      <div className="panel-header price-chart-header">
        <div>
          <p>Daily OHLCV</p>
          <div className="instrument-title">
            <h2 id="price-chart-title">{chart.symbol}</h2>
            <span>{chart.company}</span>
          </div>
        </div>
        <div className={`price-quote is-${chart.quoteTone ?? 'neutral'}`}>
          <strong>{chart.price}</strong>
          <span>{chart.change} ({chart.percent})</span>
        </div>
      </div>

      {chart.dataSourceNote && (
        <p className="price-chart-source-note">{chart.dataSourceNote}</p>
      )}

      <div className="range-selector" aria-label="Chart time range">
        {chart.ranges.map((range) => (
          <button
            className={activeRange === range ? 'is-active' : ''}
            type="button"
            key={range}
            onClick={() => onRangeChange(range)}
            aria-pressed={activeRange === range}
          >
            {range}
          </button>
        ))}
      </div>

      {isCustomMarketDataRange(activeRange) && (
        <div className="dashboard-custom-range" aria-label="Custom chart date range">
          <label>
            <span>Start</span>
            <input
              type="date"
              value={customRange?.startDate ?? ''}
              max={customRangeMaxDate}
              onChange={(event) => onCustomRangeChange('startDate', event.target.value)}
            />
          </label>
          <label>
            <span>End</span>
            <input
              type="date"
              value={customRange?.endDate ?? ''}
              max={customRangeMaxDate}
              onChange={(event) => onCustomRangeChange('endDate', event.target.value)}
            />
          </label>
          <button
            type="button"
            onClick={onCustomRangeApply}
            disabled={Boolean(customRangeError)}
          >
            Apply
          </button>
          {customRangeError && <span role="alert">{customRangeError}</span>}
        </div>
      )}

      {chart.isLoading ? (
        <ChartState>
          <strong>Loading daily OHLCV...</strong>
          <span>Fetching cached Twelve Data candles through the Django API.</span>
        </ChartState>
      ) : chart.error ? (
        <ChartState>
          <strong>Daily OHLCV unavailable.</strong>
          <span>{chart.error}</span>
        </ChartState>
      ) : chart.isEmpty ? (
        <ChartState>
          <strong>No daily OHLCV yet.</strong>
          <span>Try another range or refresh after the backend cache is populated.</span>
        </ChartState>
      ) : (
        <div
          className="price-chart is-candlestick"
          role="img"
          aria-label={`${chart.symbol} daily OHLCV candlestick chart for ${activeRange}`}
          onPointerLeave={() => setHoverState(null)}
          onPointerMove={handlePointerMove}
        >
          <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} preserveAspectRatio="none">
            {geometry.gridValues.map((value, index) => {
              const y = padding.top + (index / 4) * pricePlotHeight
              return (
                <g key={value}>
                  <line className="chart-grid-line" x1={padding.left} x2={chartWidth - padding.right} y1={y} y2={y} />
                  <text className="chart-y-label" x={padding.left - 10} y={y + 4} textAnchor="end">${value.toFixed(0)}</text>
                </g>
              )
            })}

            <line className="chart-volume-divider" x1={padding.left} x2={chartWidth - padding.right} y1={geometry.priceBottom + 12} y2={geometry.priceBottom + 12} />
            <text className="chart-y-label" x={padding.left - 10} y={geometry.volumeTop + 4} textAnchor="end">
              {formatCompactVolume(geometry.volumeMaximum)}
            </text>

            {geometry.items.map((item, index) => (
              <g className={`candle-item ${item.isUp ? 'is-up' : 'is-down'} ${hoverState?.index === index ? 'is-active' : ''}`} key={item.date}>
                <line className="candle-wick" x1={item.x} x2={item.x} y1={item.highY} y2={item.lowY} />
                <rect
                  className="candle-body"
                  x={item.x - geometry.candleWidth / 2}
                  y={item.bodyTop}
                  width={geometry.candleWidth}
                  height={item.bodyHeight}
                  rx="1"
                />
                <rect
                  className="volume-bar"
                  x={item.x - geometry.candleWidth / 2}
                  y={item.volumeY}
                  width={geometry.candleWidth}
                  height={item.volumeHeight}
                  rx="1"
                />
              </g>
            ))}

            {hoveredItem && (
              <g className="chart-crosshair" aria-hidden="true">
                <line
                  className="chart-crosshair-vertical"
                  x1={hoveredItem.x}
                  x2={hoveredItem.x}
                  y1={padding.top}
                  y2={geometry.volumeTop + volumePlotHeight}
                />
                <line
                  className="chart-crosshair-horizontal"
                  x1={padding.left}
                  x2={chartWidth - padding.right}
                  y1={hoveredItem.closeY}
                  y2={hoveredItem.closeY}
                />
              </g>
            )}

            {geometry.labelIndexes.map((index) => {
              const item = geometry.items[index]
              const label = chart.labels[index] ?? item.date
              const x = item.x
              const textAnchor = index === 0 ? 'start' : index === geometry.items.length - 1 ? 'end' : 'middle'
              return <text className="chart-x-label" x={x} y={chartHeight - 8} textAnchor={textAnchor} key={`${item.date}-${index}`}>{label}</text>
            })}
          </svg>
          {tooltip && (
            <div
              className={`chart-tooltip is-${tooltip.tone}`}
              style={{
                left: `${hoverState.tooltipLeft}px`,
                top: `${hoverState.tooltipTop}px`,
              }}
            >
              <div className="chart-tooltip-header">
                <strong>{tooltip.date}</strong>
                <span>{tooltip.change} ({tooltip.changePercent})</span>
              </div>
              <dl>
                <div><dt>Open</dt><dd>{tooltip.open}</dd></div>
                <div><dt>High</dt><dd>{tooltip.high}</dd></div>
                <div><dt>Low</dt><dd>{tooltip.low}</dd></div>
                <div><dt>Close</dt><dd>{tooltip.close}</dd></div>
                <div><dt>Volume</dt><dd>{tooltip.volume}</dd></div>
              </dl>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
