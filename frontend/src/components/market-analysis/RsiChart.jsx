import { useMemo } from 'react'
import { createDefinedLinePath, getIndicatorSeries } from './chartMath'
import IndicatorInfoTip from './IndicatorInfoTip'

const width = 1180
const height = 250
const padding = { top: 24, right: 68, bottom: 38, left: 52 }

export default function RsiChart({ stock, history, timeframeLabel }) {
  const closes = useMemo(() => history.candles.map((candle) => candle.close), [history.candles])
  const rsi = useMemo(() => getIndicatorSeries('rsi', closes).primary, [closes])
  const plotWidth = width - padding.left - padding.right
  const plotHeight = height - padding.top - padding.bottom
  const xScale = (index) => padding.left + (index / Math.max(closes.length - 1, 1)) * plotWidth
  const yScale = (value) => padding.top + ((100 - value) / 100) * plotHeight
  const currentIndex = rsi.findLastIndex((value) => Number.isFinite(value))
  const current = currentIndex >= 0 ? rsi[currentIndex] : 50
  const levels = [70, 50, 30]
  const valueBadgeWidth = 40
  const valueBadgeHeight = 20
  const currentX = xScale(Math.max(currentIndex, 0))
  const currentY = yScale(current)

  return (
    <section className="market-panel market-study-panel rsi-study-panel" aria-labelledby="rsi-study-title">
      <div className="market-panel-header rsi-panel-header">
        <div>
          <p>Independent study · Wilder</p>
          <div className="study-title-row">
            <h2 id="rsi-study-title">Relative Strength Index (RSI 14)</h2>
            <IndicatorInfoTip label="RSI (14)" align="right">
              <ul>
                <li>Above 70: Potentially overbought</li>
                <li>Below 30: Potentially oversold</li>
                <li>Around 50: Neutral momentum</li>
              </ul>
            </IndicatorInfoTip>
          </div>
        </div>
        <span className="rsi-scale-note">Fixed scale · 0–100</span>
      </div>

      <div className="study-chart rsi-chart" role="img" aria-label={`${stock.symbol} ${timeframeLabel} RSI 14 chart from 0 to 100`}>
        <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
          <rect
            className="rsi-zone is-overbought"
            x={padding.left}
            y={yScale(100)}
            width={plotWidth}
            height={yScale(70) - yScale(100)}
          />
          <rect
            className="rsi-zone is-oversold"
            x={padding.left}
            y={yScale(30)}
            width={plotWidth}
            height={yScale(0) - yScale(30)}
          />

          <text className="rsi-axis-label" x={padding.left - 8} y={yScale(100) + 4} textAnchor="end">100</text>
          <text className="rsi-axis-label" x={padding.left - 8} y={yScale(0) + 4} textAnchor="end">0</text>
          {levels.map((level) => (
            <g key={level}>
              <line
                className={`rsi-reference-line is-level-${level}`}
                x1={padding.left}
                x2={width - padding.right}
                y1={yScale(level)}
                y2={yScale(level)}
              />
              <text className={`rsi-level-label is-level-${level}`} x={padding.left - 8} y={yScale(level) + 4} textAnchor="end">
                {level}
              </text>
            </g>
          ))}

          <path className="mini-indicator-line is-rsi" d={createDefinedLinePath(rsi, xScale, yScale)} />
          <circle className="rsi-current-point" cx={currentX} cy={currentY} r="4" />
          <g className="rsi-current-badge">
            <rect
              x={currentX + 8}
              y={currentY - valueBadgeHeight / 2}
              width={valueBadgeWidth}
              height={valueBadgeHeight}
              rx="6"
            />
            <text x={currentX + 8 + valueBadgeWidth / 2} y={currentY + 3.5} textAnchor="middle">
              {current.toFixed(1)}
            </text>
          </g>

          {history.labels.map((label, index, labels) => {
            const x = padding.left + (index / Math.max(labels.length - 1, 1)) * plotWidth
            const anchor = index === 0 ? 'start' : index === labels.length - 1 ? 'end' : 'middle'
            return <text className="market-chart-label" x={x} y={height - 8} textAnchor={anchor} key={`${label}-${index}`}>{label}</text>
          })}
        </svg>
      </div>
    </section>
  )
}
