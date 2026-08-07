import { formatCompactVolume } from './chartMath'
import useMarketChartViewportInteraction from './useMarketChartViewportInteraction'

const width = 860
const height = 154
const padding = { top: 14, right: 22, bottom: 30, left: 58 }

export default function VolumeChart({
  fullCandleCount,
  history,
  interval,
  onVisibleWindowChange,
  onVisibleWindowReset,
  rangeLabel,
  stock,
  visibleWindow,
}) {
  const volumes = history.candles.map((candle) => candle.volume)
  const maximum = Math.max(...volumes.filter(Number.isFinite), 1)
  const average = volumes.reduce((sum, value) => sum + value, 0) / volumes.length
  const current = volumes.at(-1)
  const activityRatio = current / Math.max(average, 1)
  const activity = activityRatio > 1.25 ? 'Elevated' : activityRatio < 0.75 ? 'Quiet' : 'Normal'
  const plotWidth = width - padding.left - padding.right
  const plotHeight = height - padding.top - padding.bottom
  const slotWidth = plotWidth / volumes.length
  const barWidth = Math.max(slotWidth * 0.58, 4)
  const {
    chartContainerRef,
    handlePointerDown,
    handlePointerUp,
    handleViewportPointerMove,
    isDragging,
    isFullView,
    resetVisibleWindow,
  } = useMarketChartViewportInteraction({
    chartWidth: width,
    onVisibleWindowChange,
    onVisibleWindowReset,
    plotLeft: padding.left,
    plotWidth,
    totalCandles: fullCandleCount ?? history.candles.length,
    visibleWindow,
  })

  return (
    <section className="market-panel market-volume-panel" aria-labelledby="volume-title">
      <div className="market-panel-header volume-header">
        <div>
          <p>Detailed volume view</p>
          <h2 id="volume-title">Volume Analysis</h2>
        </div>
        <div className="volume-summary">
          <span>Average Volume <strong>{formatCompactVolume(average)}</strong></span>
          <span>Peak Volume <strong>{formatCompactVolume(maximum)}</strong></span>
          <span>Current Volume <strong>{formatCompactVolume(current)}</strong></span>
          <span>Volume Activity <strong className={activity === 'Elevated' ? 'is-warning' : 'is-neutral'}>{activity}</strong></span>
          <button
            className="market-chart-reset-button"
            type="button"
            onClick={resetVisibleWindow}
            disabled={isFullView}
          >
            Reset view
          </button>
        </div>
      </div>

      <div
        ref={chartContainerRef}
        className={`volume-chart ${isDragging ? 'is-dragging' : ''}`.trim()}
        role="img"
        aria-label={`${stock.symbol} ${rangeLabel} range with ${interval} bars detailed volume analysis chart`}
        onDoubleClick={resetVisibleWindow}
        onPointerCancel={handlePointerUp}
        onPointerDown={handlePointerDown}
        onPointerMove={handleViewportPointerMove}
        onPointerUp={handlePointerUp}
      >
        <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
          {[0, 0.5, 1].map((position) => {
            const y = padding.top + position * plotHeight
            const label = maximum * (1 - position)
            return (
              <g key={position}>
                <line className="market-chart-grid" x1={padding.left} x2={width - padding.right} y1={y} y2={y} />
                <text className="market-chart-label" x={padding.left - 10} y={y + 4} textAnchor="end">{formatCompactVolume(label)}</text>
              </g>
            )
          })}

          {history.candles.map((candle, index) => {
            const volume = candle.volume
            const barHeight = (volume / maximum) * plotHeight
            const x = padding.left + index * slotWidth + (slotWidth - barWidth) / 2
            const y = padding.top + plotHeight - barHeight
            const isUp = candle.close >= candle.open
            return <rect className={isUp ? 'volume-bar is-up' : 'volume-bar is-down'} x={x} y={y} width={barWidth} height={barHeight} rx="2" key={candle.id} />
          })}

          {history.labels.map((label, index, labels) => {
            const x = padding.left + (index / (labels.length - 1)) * plotWidth
            const anchor = index === 0 ? 'start' : index === labels.length - 1 ? 'end' : 'middle'
            return <text className="market-chart-label" x={x} y={height - 7} textAnchor={anchor} key={`${label}-${index}`}>{label}</text>
          })}
        </svg>
      </div>
    </section>
  )
}
