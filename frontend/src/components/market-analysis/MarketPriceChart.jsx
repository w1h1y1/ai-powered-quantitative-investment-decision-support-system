import { useEffect, useMemo, useState } from 'react'
import {
  bollingerOverlaySeries,
  createDefinedLinePath,
  exponentialMovingAverage,
  formatCompactVolume,
  movingAverageSeries,
} from './chartMath'

const width = 860
const height = 470
const padding = { top: 22, right: 28, bottom: 38, left: 62 }
const pricePlotHeight = 294
const volumePlotTop = 340
const volumePlotHeight = 84
const volumePlotBottom = volumePlotTop + volumePlotHeight
const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function buildOverlaySeries(closes, options, selectedOverlays) {
  return Object.fromEntries(
    options
      .filter((option) => selectedOverlays.includes(option.id))
      .map((option) => {
        if (option.type === 'ma') return [option.id, { primary: movingAverageSeries(closes, option.period) }]
        if (option.type === 'ema') return [option.id, { primary: exponentialMovingAverage(closes, option.period) }]
        return [option.id, bollingerOverlaySeries(closes, option.period, 2)]
      }),
  )
}

function buildChartGeometry(candles, overlaySeries) {
  const domainValues = candles.flatMap((candle) => [candle.high, candle.low])

  Object.values(overlaySeries).forEach((series) => {
    const values = series.upper ? [...series.upper, ...series.lower] : series.primary
    domainValues.push(...values.filter((value) => Number.isFinite(value)))
  })

  const rawMinimum = Math.min(...domainValues)
  const rawMaximum = Math.max(...domainValues)
  const buffer = Math.max((rawMaximum - rawMinimum) * 0.08, 0.5)
  const minimum = rawMinimum - buffer
  const maximum = rawMaximum + buffer
  const plotWidth = width - padding.left - padding.right
  const slotWidth = plotWidth / Math.max(candles.length, 1)
  const candleWidth = Math.max(Math.min(slotWidth * 0.58, 12), 3)
  const xScale = (index) => padding.left + (index + 0.5) * slotWidth
  const yScale = (value) => padding.top + ((maximum - value) / (maximum - minimum)) * pricePlotHeight
  const gridValues = Array.from({ length: 5 }, (_, index) => maximum - ((maximum - minimum) / 4) * index)

  return { minimum, maximum, plotWidth, slotWidth, candleWidth, xScale, yScale, gridValues }
}

function buildVolumeGeometry(candles, chartGeometry) {
  const maximum = Math.max(...candles.map((candle) => candle.volume), 1)
  const barWidth = Math.max(Math.min(chartGeometry.slotWidth * 0.58, 12), 3)
  const yScale = (value) => volumePlotBottom - (value / maximum) * volumePlotHeight
  return { maximum, barWidth, yScale, gridValues: [maximum, maximum / 2, 0] }
}

function createBandPath(upper, lower, xScale, yScale) {
  const indices = upper
    .map((value, index) => Number.isFinite(value) && Number.isFinite(lower[index]) ? index : null)
    .filter((index) => index !== null)

  if (indices.length === 0) return ''

  const upperPath = indices
    .map((index, position) => `${position === 0 ? 'M' : 'L'} ${xScale(index)} ${yScale(upper[index])}`)
    .join(' ')
  const lowerPath = [...indices]
    .reverse()
    .map((index) => `L ${xScale(index)} ${yScale(lower[index])}`)
    .join(' ')
  return `${upperPath} ${lowerPath} Z`
}

function formatPrice(value) {
  return Number.isFinite(value) ? `$${value.toFixed(2)}` : '—'
}

function formatTooltipVolume(value) {
  if (value >= 1000000) return `${(value / 1000000).toFixed(2)}M`
  if (value >= 1000) return `${Math.round(value / 1000)}K`
  return String(value)
}

function formatDateTime(timestamp) {
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return 'Mock period'
  const day = String(date.getUTCDate()).padStart(2, '0')
  const hours = String(date.getUTCHours()).padStart(2, '0')
  const minutes = String(date.getUTCMinutes()).padStart(2, '0')
  return `${day} ${monthNames[date.getUTCMonth()]} ${date.getUTCFullYear()}, ${hours}:${minutes}`
}

function getHoverIndicators(options, selectedOverlays, overlaySeries, index) {
  return options
    .filter((option) => selectedOverlays.includes(option.id))
    .flatMap((option) => {
      const series = overlaySeries[option.id]
      if (option.type === 'bollinger') {
        return [
          { label: 'Bollinger Upper', value: series.upper[index] },
          { label: 'Bollinger Middle', value: series.middle[index] },
          { label: 'Bollinger Lower', value: series.lower[index] },
        ]
      }
      return [{ label: option.label, value: series.primary[index] }]
    })
}

export default function MarketPriceChart({
  stock,
  history,
  rangeLabel,
  interval,
  overlayOptions,
  selectedOverlays,
}) {
  const [hoveredIndex, setHoveredIndex] = useState(null)
  const closes = useMemo(() => history.candles.map((candle) => candle.close), [history.candles])
  const overlaySeries = useMemo(
    () => buildOverlaySeries(closes, overlayOptions, selectedOverlays),
    [closes, overlayOptions, selectedOverlays],
  )
  const geometry = useMemo(
    () => buildChartGeometry(history.candles, overlaySeries),
    [history.candles, overlaySeries],
  )
  const volumeGeometry = useMemo(
    () => buildVolumeGeometry(history.candles, geometry),
    [geometry, history.candles],
  )

  useEffect(() => setHoveredIndex(null), [history, interval, rangeLabel, stock.symbol])

  const latestCandle = history.candles.at(-1)
  const bollinger = overlaySeries.bollinger20
  const hoveredCandle = hoveredIndex === null ? null : history.candles[hoveredIndex]
  const hoveredIndicators = hoveredIndex === null
    ? []
    : getHoverIndicators(overlayOptions, selectedOverlays, overlaySeries, hoveredIndex)

  return (
    <section
      className="market-panel market-price-panel"
      aria-labelledby="market-price-title"
      data-range={rangeLabel}
      data-interval={interval}
    >
      <div className="market-panel-header market-price-header">
        <div>
          <p>Candlestick chart · {rangeLabel} · {interval} bars</p>
          <div className="market-instrument-name">
            <h2 id="market-price-title">{stock.symbol}</h2>
            <span>{stock.company} · {stock.exchange}</span>
          </div>
        </div>
        <div className="market-live-quote">
          <strong>{stock.formattedPrice}</strong>
          <span className={`is-${stock.direction}`}>{stock.change} ({stock.percent})</span>
        </div>
      </div>

      <div className="market-chart-legend" aria-label="Candlestick chart legend">
        <span><i className="is-candles" /> K Line</span>
        {overlayOptions
          .filter((option) => selectedOverlays.includes(option.id))
          .map((option) => (
            <span key={option.id}>
              <i className={`is-${option.id}`} /> {option.legendLabel ?? option.label}
            </span>
          ))}
      </div>

      <div
        className="market-price-chart candlestick-chart"
        role="img"
        aria-label={`${stock.symbol} ${rangeLabel} range with ${interval} bars candlestick and aligned volume chart with ${selectedOverlays.length} overlays`}
        data-hovered-index={hoveredIndex ?? ''}
        onPointerLeave={() => setHoveredIndex(null)}
      >
        <div className="candlestick-chart-stage">
          <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
          {geometry.gridValues.map((value, index) => {
            const y = padding.top + (index / 4) * pricePlotHeight
            return (
              <g key={`${value}-${index}`}>
                <line className="market-chart-grid" x1={padding.left} x2={width - padding.right} y1={y} y2={y} />
                <text className="market-chart-label" x={padding.left - 11} y={y + 4} textAnchor="end">${value.toFixed(0)}</text>
              </g>
            )
          })}

          {bollinger && (
            <>
              <path className="bollinger-area" d={createBandPath(bollinger.upper, bollinger.lower, geometry.xScale, geometry.yScale)} />
              <path className="kline-overlay is-bollinger-upper" d={createDefinedLinePath(bollinger.upper, geometry.xScale, geometry.yScale)} />
              <path className="kline-overlay is-bollinger-middle" d={createDefinedLinePath(bollinger.middle, geometry.xScale, geometry.yScale)} />
              <path className="kline-overlay is-bollinger-lower" d={createDefinedLinePath(bollinger.lower, geometry.xScale, geometry.yScale)} />
            </>
          )}

          {history.candles.map((candle, index) => {
            const isRising = candle.close >= candle.open
            const bodyTop = geometry.yScale(Math.max(candle.open, candle.close))
            const bodyHeight = Math.max(Math.abs(geometry.yScale(candle.open) - geometry.yScale(candle.close)), 1.2)
            return (
              <g className={`candlestick ${isRising ? 'is-rising' : 'is-falling'} ${hoveredIndex === index ? 'is-hovered' : ''}`} key={candle.id}>
                <line
                  className="candlestick-wick"
                  x1={geometry.xScale(index)}
                  x2={geometry.xScale(index)}
                  y1={geometry.yScale(candle.high)}
                  y2={geometry.yScale(candle.low)}
                />
                <rect
                  className="candlestick-body"
                  x={geometry.xScale(index) - geometry.candleWidth / 2}
                  y={bodyTop}
                  width={geometry.candleWidth}
                  height={bodyHeight}
                  rx="1"
                />
              </g>
            )
          })}

          {overlayOptions
            .filter((option) => selectedOverlays.includes(option.id) && option.type !== 'bollinger')
            .map((option) => (
              <path
                className={`kline-overlay is-${option.id}`}
                d={createDefinedLinePath(overlaySeries[option.id].primary, geometry.xScale, geometry.yScale)}
                key={option.id}
              />
            ))}

          <line className="inline-volume-divider" x1={padding.left} x2={width - padding.right} y1={volumePlotTop - 14} y2={volumePlotTop - 14} />
          <text className="inline-volume-title" x={padding.left} y={volumePlotTop - 5}>Volume</text>
          {volumeGeometry.gridValues.map((value, index) => {
            const y = volumePlotTop + (index / 2) * volumePlotHeight
            return (
              <g key={`volume-grid-${index}`}>
                <line className="inline-volume-grid" x1={padding.left} x2={width - padding.right} y1={y} y2={y} />
                <text className="market-chart-label" x={padding.left - 11} y={y + 4} textAnchor="end">{formatCompactVolume(value)}</text>
              </g>
            )
          })}

          {history.candles.map((candle, index) => {
            const y = volumeGeometry.yScale(candle.volume)
            const isRising = candle.close >= candle.open
            return (
              <rect
                className={`inline-volume-bar ${isRising ? 'is-up' : 'is-down'} ${hoveredIndex === index ? 'is-hovered' : ''}`}
                x={geometry.xScale(index) - volumeGeometry.barWidth / 2}
                y={y}
                width={volumeGeometry.barWidth}
                height={Math.max(volumePlotBottom - y, 1)}
                rx="1.5"
                key={`inline-volume-${candle.id}`}
              />
            )
          })}

          {hoveredIndex !== null && (
            <line
              className="chart-hover-line"
              x1={geometry.xScale(hoveredIndex)}
              x2={geometry.xScale(hoveredIndex)}
              y1={padding.top}
              y2={volumePlotBottom}
            />
          )}

          {history.labels.map((label, index, labels) => {
            const candleIndex = Math.round((index / Math.max(labels.length - 1, 1)) * (history.candles.length - 1))
            const x = geometry.xScale(candleIndex)
            const anchor = index === 0 ? 'start' : index === labels.length - 1 ? 'end' : 'middle'
            return <text className="market-chart-label" x={x} y={height - 10} textAnchor={anchor} key={`${label}-${index}`}>{label}</text>
          })}

          {history.candles.map((candle, index) => (
            <rect
              className="chart-hover-target"
              data-candle-index={index}
              x={geometry.xScale(index) - geometry.slotWidth / 2}
              y={padding.top}
              width={geometry.slotWidth}
              height={volumePlotBottom - padding.top}
              onPointerEnter={() => setHoveredIndex(index)}
              onPointerDown={() => setHoveredIndex(index)}
              key={`hover-${candle.id}`}
            />
          ))}
          </svg>

          {hoveredCandle && (
            <div
              className={`chart-hover-tooltip ${geometry.xScale(hoveredIndex) > width * 0.62 ? 'is-left' : ''}`}
              style={{ left: `${(geometry.xScale(hoveredIndex) / width) * 100}%` }}
              role="tooltip"
            >
              <div className="chart-hover-date"><span>Date / Time</span><strong>{formatDateTime(hoveredCandle.timestamp)}</strong></div>
              <dl>
                <div><dt>Open</dt><dd>{formatPrice(hoveredCandle.open)}</dd></div>
                <div><dt>High</dt><dd>{formatPrice(hoveredCandle.high)}</dd></div>
                <div><dt>Low</dt><dd>{formatPrice(hoveredCandle.low)}</dd></div>
                <div><dt>Close</dt><dd>{formatPrice(hoveredCandle.close)}</dd></div>
                <div><dt>Volume</dt><dd>{formatTooltipVolume(hoveredCandle.volume)}</dd></div>
                {hoveredIndicators.map((indicator) => (
                  <div key={indicator.label}><dt>{indicator.label}</dt><dd>{formatPrice(indicator.value)}</dd></div>
                ))}
              </dl>
            </div>
          )}
        </div>
      </div>

      <div className="market-stat-strip is-five-column">
        <div><span>Open</span><strong>{formatPrice(latestCandle.open)}</strong></div>
        <div><span>High</span><strong>{formatPrice(latestCandle.high)}</strong></div>
        <div><span>Low</span><strong>{formatPrice(latestCandle.low)}</strong></div>
        <div><span>Close</span><strong>{formatPrice(latestCandle.close)}</strong></div>
        <div><span>Market cap</span><strong>{stock.stats.marketCap}</strong></div>
      </div>
    </section>
  )
}
