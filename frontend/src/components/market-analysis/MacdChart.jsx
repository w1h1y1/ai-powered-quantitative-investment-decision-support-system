import { useMemo } from 'react'
import { createDefinedLinePath, getIndicatorSeries } from './chartMath'
import IndicatorInfoTip from './IndicatorInfoTip'
import useMarketChartViewportInteraction from './useMarketChartViewportInteraction'

const width = 620
const height = 230
const padding = { top: 24, right: 20, bottom: 36, left: 48 }

export default function MacdChart({
  fullCandleCount,
  history,
  onVisibleWindowChange,
  onVisibleWindowReset,
  stock,
  timeframeLabel,
  visibleWindow,
}) {
  const closes = useMemo(() => history.candles.map((candle) => candle.close), [history.candles])
  const series = useMemo(() => {
    if (history.indicators?.length) {
      return {
        dif: history.indicators.map((indicator) => indicator.macd),
        dea: history.indicators.map((indicator) => indicator.signal),
        histogram: history.indicators.map((indicator) => indicator.histogram),
      }
    }

    return getIndicatorSeries('macd', closes)
  }, [closes, history.indicators])
  const geometry = useMemo(() => {
    const finiteValues = [...series.dif, ...series.dea, ...series.histogram]
      .filter((value) => Number.isFinite(value))
    const bound = Math.max(
      ...finiteValues.map((value) => Math.abs(value)),
      0.01,
    ) * 1.14
    const plotWidth = width - padding.left - padding.right
    const plotHeight = height - padding.top - padding.bottom
    const xScale = (index) => padding.left + (index / Math.max(closes.length - 1, 1)) * plotWidth
    const yScale = (value) => padding.top + ((bound - value) / (bound * 2)) * plotHeight
    return { bound, plotWidth, plotHeight, xScale, yScale }
  }, [closes.length, series])
  const zeroY = geometry.yScale(0)
  const slotWidth = geometry.plotWidth / history.candles.length
  const barWidth = Math.max(slotWidth * 0.54, 2.5)
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
    plotWidth: geometry.plotWidth,
    totalCandles: fullCandleCount ?? history.candles.length,
    visibleWindow,
  })
  const latestHistogramIndex = series.histogram.findLastIndex((value) => Number.isFinite(value))
  const currentDif = latestHistogramIndex >= 0 ? series.dif[latestHistogramIndex] : null
  const currentHistogram = latestHistogramIndex >= 0 ? series.histogram[latestHistogramIndex] : null
  const signal = currentHistogram === null
    ? 'Insufficient history'
    : currentHistogram >= 0 ? 'Bullish momentum' : 'Bearish momentum'

  return (
    <section className="market-panel market-study-panel macd-study-panel" aria-labelledby="macd-study-title">
      <div className="market-panel-header study-panel-header">
        <div>
          <p>Independent study</p>
          <div className="study-title-row">
            <h2 id="macd-study-title">MACD <small>(12, 26, 9)</small></h2>
            <IndicatorInfoTip label="MACD (12, 26, 9)">
              <ul>
                <li>DIF above DEA: Bullish momentum</li>
                <li>DIF below DEA: Bearish momentum</li>
                <li>Histogram shows the distance between DIF and DEA</li>
              </ul>
            </IndicatorInfoTip>
          </div>
        </div>
        <div className="study-current-value">
          <small>DIF Value</small>
          <strong>{Number.isFinite(currentDif) ? currentDif.toFixed(2) : 'N/A'}</strong>
          <span className={currentHistogram === null ? 'is-neutral' : currentHistogram >= 0 ? 'is-positive' : 'is-negative'}>{signal}</span>
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

      <div className="study-legend">
        <span><i className="is-dif" /> DIF</span>
        <span><i className="is-dea" /> DEA</span>
        <span><i className="is-histogram" /> Histogram</span>
      </div>

      <div
        ref={chartContainerRef}
        className={`study-chart macd-chart ${isDragging ? 'is-dragging' : ''}`.trim()}
        role="img"
        aria-label={`${stock.symbol} ${timeframeLabel} MACD 12 26 9 chart`}
        onDoubleClick={resetVisibleWindow}
        onPointerCancel={handlePointerUp}
        onPointerDown={handlePointerDown}
        onPointerMove={handleViewportPointerMove}
        onPointerUp={handlePointerUp}
      >
        <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
          {[0, 0.5, 1].map((position) => {
            const y = padding.top + position * geometry.plotHeight
            return <line className="market-chart-grid" x1={padding.left} x2={width - padding.right} y1={y} y2={y} key={position} />
          })}
          {series.histogram.map((value, index) => {
            if (!Number.isFinite(value)) return null
            const valueY = geometry.yScale(value)
            return (
              <rect
                className={`macd-histogram-bar ${value >= 0 ? 'is-positive' : 'is-negative'}`}
                x={geometry.xScale(index) - barWidth / 2}
                y={Math.min(valueY, zeroY)}
                width={barWidth}
                height={Math.abs(valueY - zeroY)}
                rx="1"
                key={history.candles[index].id}
              />
            )
          })}
          <line className="indicator-zero-line" x1={padding.left} x2={width - padding.right} y1={zeroY} y2={zeroY} />
          <text className="indicator-zero-label" x={padding.left + 3} y={zeroY - 4}>0</text>
          <path className="macd-line is-dif" d={createDefinedLinePath(series.dif, geometry.xScale, geometry.yScale)} />
          <path className="macd-line is-dea" d={createDefinedLinePath(series.dea, geometry.xScale, geometry.yScale)} />
          {history.labels.map((label, index, labels) => {
            const x = padding.left + (index / (labels.length - 1)) * geometry.plotWidth
            const anchor = index === 0 ? 'start' : index === labels.length - 1 ? 'end' : 'middle'
            return <text className="market-chart-label" x={x} y={height - 8} textAnchor={anchor} key={`${label}-${index}`}>{label}</text>
          })}
        </svg>
      </div>
    </section>
  )
}
