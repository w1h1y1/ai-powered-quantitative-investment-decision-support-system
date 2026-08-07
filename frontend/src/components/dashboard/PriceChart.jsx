import { useEffect, useMemo, useRef, useState } from 'react'
import {
  dashboardMarketDataIntervals,
  formatDashboardCandleTooltip,
  isCustomMarketDataRange,
  normalizeDashboardVisibleWindow,
  panDashboardVisibleWindow,
  zoomDashboardVisibleWindow,
} from './dashboardSecurityModel'

const chartWidth = 720
const padding = { top: 18, right: 112, bottom: 32, left: 56 }
const basePlotHeight = 468
const panelGap = 14
const panelHeightShares = { volume: 0.12, macd: 0.20, rsi: 0.13 }
const tooltipWidth = 218
const tooltipHeight = 180
const maximumCandleWidth = 14
const chartTypeOptions = [
  { label: 'Candlestick', value: 'candlestick' },
  { label: 'Line', value: 'line' },
]

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

function formatIndicatorValue(value, digits = 2) {
  return Number.isFinite(value) ? value.toFixed(digits) : '--'
}

function formatAxisPrice(value) {
  return Number.isFinite(value) ? value.toFixed(2) : ''
}

function createLabelIndexes(count, plotWidth) {
  if (count <= 0) return []

  const maxLabelCount = Math.max(2, Math.min(6, Math.floor(plotWidth / 120)))
  if (count <= maxLabelCount) {
    return Array.from({ length: count }, (_, index) => index)
  }

  return Array.from(new Set(
    Array.from({ length: maxLabelCount }, (_, index) => (
      Math.round((index * (count - 1)) / (maxLabelCount - 1))
    )),
  )).sort((left, right) => left - right)
}

function finiteValues(values) {
  return values.filter((value) => Number.isFinite(value))
}

function createScale(minimum, maximum, top, height) {
  const valueRange = Math.max(maximum - minimum, 0.000001)
  return (value) => top + ((maximum - value) / valueRange) * height
}

function createLinePath(items, yField) {
  let path = ''
  let isDrawing = false

  items.forEach((item) => {
    const y = item[yField]
    if (!Number.isFinite(y)) {
      isDrawing = false
      return
    }
    path += `${isDrawing ? ' L' : 'M'} ${item.x.toFixed(2)} ${y.toFixed(2)}`
    isDrawing = true
  })

  return path
}

function createAreaPath(items, yField, baselineY) {
  const path = createLinePath(items, yField)
  if (!path || !items.length) return ''

  const firstItem = items.find((item) => Number.isFinite(item[yField]))
  const lastItem = [...items].reverse().find((item) => Number.isFinite(item[yField]))
  if (!firstItem || !lastItem) return ''

  return `${path} L ${lastItem.x.toFixed(2)} ${baselineY.toFixed(2)} L ${firstItem.x.toFixed(2)} ${baselineY.toFixed(2)} Z`
}

function createPanelLayout(visiblePanels) {
  const lowerPanels = [
    visiblePanels.volume ? 'volume' : null,
    visiblePanels.macd ? 'macd' : null,
    visiblePanels.rsi ? 'rsi' : null,
  ].filter(Boolean)
  const gapHeight = lowerPanels.length * panelGap
  const availableHeight = basePlotHeight - gapHeight
  const lowerHeights = lowerPanels.reduce((heights, panel) => ({
    ...heights,
    [panel]: Math.max(44, Math.round(availableHeight * panelHeightShares[panel])),
  }), {})
  const lowerHeight = Object.values(lowerHeights).reduce((total, height) => total + height, 0)
  const priceHeight = Math.max(220, availableHeight - lowerHeight)
  const panels = {}
  let cursor = padding.top

  panels.price = {
    top: cursor,
    height: priceHeight,
    bottom: cursor + priceHeight,
  }
  cursor = panels.price.bottom

  lowerPanels.forEach((panel) => {
    cursor += panelGap
    panels[panel] = {
      top: cursor,
      height: lowerHeights[panel],
      bottom: cursor + lowerHeights[panel],
    }
    cursor = panels[panel].bottom
  })

  return {
    chartHeight: cursor + padding.bottom,
    panels,
  }
}

function createChartGeometry(candles, indicators, visiblePanels, chartType) {
  const { chartHeight, panels } = createPanelLayout(visiblePanels)
  const isLineChart = chartType === 'line'
  const priceMaximumValues = candles.map((candle) => (isLineChart ? candle.close : candle.high))
  const priceMinimumValues = candles.map((candle) => (isLineChart ? candle.close : candle.low))
  const rawMinimum = Math.min(...priceMinimumValues)
  const rawMaximum = Math.max(...priceMaximumValues)
  const buffer = Math.max((rawMaximum - rawMinimum) * 0.12, 0.01)
  const minimum = rawMinimum - buffer
  const maximum = rawMaximum + buffer
  const plotWidth = chartWidth - padding.left - padding.right
  const plotRight = chartWidth - padding.right
  const axisLabelX = plotRight + 8
  const candleStep = candles.length > 1 ? plotWidth / (candles.length - 1) : plotWidth
  const candleWidth = Math.max(2, Math.min(maximumCandleWidth, candleStep * 0.56))
  const scalePrice = createScale(minimum, maximum, panels.price.top, panels.price.height)
  const volumeMaximum = Math.max(...candles.map((candle) => candle.volume), 1)
  const scaleVolume = (value) => (value / volumeMaximum) * (panels.volume?.height ?? 0)

  const macdValues = finiteValues(indicators.flatMap((indicator) => [
    indicator.macd,
    indicator.signal,
    indicator.histogram,
  ]))
  const scaledMacdValues = macdValues.length ? [
    ...macdValues,
    0,
  ] : []
  const macdMinimum = scaledMacdValues.length ? Math.min(...scaledMacdValues) : -1
  const macdMaximum = scaledMacdValues.length ? Math.max(...scaledMacdValues) : 1
  const macdBuffer = Math.max((macdMaximum - macdMinimum) * 0.16, 0.1)
  const macdScaleMinimum = macdMinimum - macdBuffer
  const macdScaleMaximum = macdMaximum + macdBuffer
  const scaleMacd = panels.macd
    ? createScale(macdScaleMinimum, macdScaleMaximum, panels.macd.top, panels.macd.height)
    : null
  const scaleRsi = panels.rsi ? createScale(0, 100, panels.rsi.top, panels.rsi.height) : null

  const items = candles.map((candle, index) => {
    const indicator = indicators[index] ?? {}
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
    const volumeHeight = panels.volume ? Math.max(scaleVolume(candle.volume), 1) : 0
    const histogramZeroY = scaleMacd ? scaleMacd(0) : null
    const histogramY = scaleMacd && Number.isFinite(indicator.histogram)
      ? scaleMacd(indicator.histogram)
      : null

    return {
      ...candle,
      ...indicator,
      index,
      x,
      openY,
      closeY,
      highY,
      lowY,
      isUp,
      bodyTop,
      bodyHeight,
      volumeHeight,
      volumeY: panels.volume ? panels.volume.bottom - volumeHeight : null,
      macdY: scaleMacd && Number.isFinite(indicator.macd) ? scaleMacd(indicator.macd) : null,
      signalY: scaleMacd && Number.isFinite(indicator.signal) ? scaleMacd(indicator.signal) : null,
      histogramY,
      histogramZeroY,
      histogramHeight: histogramY === null ? 0 : Math.max(Math.abs(histogramZeroY - histogramY), 1),
      rsiY: scaleRsi && Number.isFinite(indicator.rsi) ? scaleRsi(indicator.rsi) : null,
    }
  })
  const hasMacdData = items.some((item) => (
    Number.isFinite(item.macd)
    && Number.isFinite(item.signal)
    && Number.isFinite(item.histogram)
  ))
  const hasRsiData = items.some((item) => Number.isFinite(item.rsi))

  return {
    axisLabelX,
    candleWidth,
    chartHeight,
    hasMacdData,
    hasRsiData,
    items,
    labelIndexes: createLabelIndexes(candles.length, plotWidth),
    lineAreaPath: createAreaPath(items, 'closeY', panels.price.bottom),
    linePath: createLinePath(items, 'closeY'),
    macdAxisItems: panels.macd ? [macdScaleMaximum, 0, macdScaleMinimum].map((value) => ({
      value,
      y: scaleMacd(value),
    })) : [],
    macdLinePath: createLinePath(items, 'macdY'),
    panels,
    plotRight,
    plotWidth,
    priceAxisValues: Array.from({ length: 5 }, (_, index) => maximum - ((maximum - minimum) / 4) * index),
    rsiAxisItems: panels.rsi ? [100, 70, 30, 0].map((value) => ({
      value,
      y: scaleRsi(value),
    })) : [],
    rsiLinePath: createLinePath(items, 'rsiY'),
    signalLinePath: createLinePath(items, 'signalY'),
    volumeMaximum,
    volumeAxisItems: panels.volume ? [
      { value: volumeMaximum, y: panels.volume.top + 10 },
      { value: 0, y: panels.volume.bottom - 4 },
    ] : [],
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
  isCustomRangeOpen,
  onCustomRangeApply,
  onCustomRangeCancel,
  onCustomRangeChange,
  onIntervalChange,
  onRangeChange,
  selectedInterval,
  selectedRange,
}) {
  const activeRange = chart.ranges.includes(selectedRange) ? selectedRange : chart.ranges[0]
  const candles = chart.candles ?? []
  const indicators = chart.indicators ?? []
  const indicatorWarnings = chart.indicatorWarnings ?? {}
  const intervalOptions = chart.intervalOptions ?? dashboardMarketDataIntervals
  const hasCandles = candles.length > 0
  const [hoverState, setHoverState] = useState(null)
  const [visibleWindow, setVisibleWindow] = useState(null)
  const [visiblePanels, setVisiblePanels] = useState({ volume: true, macd: true, rsi: true })
  const [chartType, setChartType] = useState('candlestick')
  const [isDragging, setIsDragging] = useState(false)
  const dragRef = useRef(null)
  const chartContainerRef = useRef(null)
  const isLineChart = chartType === 'line'

  useEffect(() => {
    setVisibleWindow(null)
    setHoverState(null)
    setIsDragging(false)
  }, [activeRange, chart.dataKey, chart.interval, chart.symbol])

  const normalizedWindow = normalizeDashboardVisibleWindow(visibleWindow, candles.length)
  const isFullView = !hasCandles || (normalizedWindow.start === 0 && normalizedWindow.end === candles.length - 1)
  const visibleCandles = candles.slice(normalizedWindow.start, normalizedWindow.end + 1)
  const visibleIndicators = indicators.slice(normalizedWindow.start, normalizedWindow.end + 1)
  const geometry = useMemo(
    () => (hasCandles ? createChartGeometry(visibleCandles, visibleIndicators, visiblePanels, chartType) : null),
    [chartType, hasCandles, visibleCandles, visibleIndicators, visiblePanels],
  )
  const hoveredItem = hoverState && geometry ? geometry.items[hoverState.index] : null
  const activeItem = hoveredItem ?? geometry?.items.at(-1) ?? null
  const tooltip = hoveredItem ? formatDashboardCandleTooltip(hoveredItem, chart.currency) : null
  const activePriceMarkerY = activeItem && geometry
    ? clamp(activeItem.closeY, geometry.panels.price.top + 10, geometry.panels.price.bottom - 6)
    : null

  const resetVisibleWindow = () => {
    dragRef.current = null
    setVisibleWindow(null)
    setHoverState(null)
    setIsDragging(false)
  }

  const getPointerChartPosition = (event) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    if (!bounds.width || !bounds.height) return null

    const relativeX = event.clientX - bounds.left
    const relativeY = event.clientY - bounds.top
    return {
      bounds,
      chartX: (relativeX / bounds.width) * chartWidth,
      relativeX,
      relativeY,
    }
  }

  const updateHoverFromPointer = (event) => {
    if (!geometry?.items.length) return
    const position = getPointerChartPosition(event)
    if (!position) return

    const rawIndex = geometry.items.length > 1
      ? Math.round(((position.chartX - padding.left) / geometry.plotWidth) * (geometry.items.length - 1))
      : 0
    const index = clamp(rawIndex, 0, geometry.items.length - 1)
    const tooltipLeft = clamp(position.relativeX + 14, 8, Math.max(8, position.bounds.width - tooltipWidth - 8))
    const tooltipTopCandidate = position.relativeY > tooltipHeight + 28
      ? position.relativeY - tooltipHeight - 14
      : position.relativeY + 14
    const tooltipTop = clamp(tooltipTopCandidate, 8, Math.max(8, position.bounds.height - tooltipHeight - 8))

    setHoverState({
      index,
      tooltipLeft,
      tooltipTop,
    })
  }

  const handlePointerMove = (event) => {
    if (!geometry?.items.length) return
    updateHoverFromPointer(event)
    if (!dragRef.current || !candles.length) return
    event.preventDefault()

    const current = normalizeDashboardVisibleWindow(visibleWindow, candles.length)
    const candleCount = current.end - current.start + 1
    if (candleCount >= candles.length) return

    const position = getPointerChartPosition(event)
    if (!position) return

    const renderedPlotWidth = position.bounds.width * (geometry.plotWidth / chartWidth)
    const pixelStep = Math.max(renderedPlotWidth / Math.max(candleCount - 1, 1), 1)
    const shift = Math.round((dragRef.current.clientX - event.clientX) / pixelStep)
    if (!shift) return

    setVisibleWindow(() => panDashboardVisibleWindow({
      window: {
        start: dragRef.current.start,
        end: dragRef.current.end,
      },
      total: candles.length,
      shift,
    }))
  }

  const handlePointerDown = (event) => {
    if (!hasCandles || event.button !== 0) return
    event.preventDefault()
    const current = normalizeDashboardVisibleWindow(visibleWindow, candles.length)
    dragRef.current = {
      clientX: event.clientX,
      start: current.start,
      end: current.end,
    }
    setIsDragging(true)
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }

  const handlePointerUp = (event) => {
    dragRef.current = null
    setIsDragging(false)
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  const handleWheel = (event) => {
    if (!geometry?.items.length) return
    event.preventDefault()
    event.stopPropagation()
    if (!event.deltaY) return

    const position = getPointerChartPosition(event)
    if (!position) return

    const anchorRatio = clamp((position.chartX - padding.left) / geometry.plotWidth, 0, 1)
    setVisibleWindow((currentWindow) => zoomDashboardVisibleWindow({
      window: currentWindow,
      total: candles.length,
      anchorRatio,
      deltaY: event.deltaY,
    }))
  }

  useEffect(() => {
    const chartElement = chartContainerRef.current
    if (!chartElement || !hasCandles) return undefined

    chartElement.addEventListener('wheel', handleWheel, { passive: false })
    return () => {
      chartElement.removeEventListener('wheel', handleWheel)
    }
  }, [handleWheel, hasCandles])

  const togglePanel = (panel) => {
    setVisiblePanels((currentPanels) => ({
      ...currentPanels,
      [panel]: !currentPanels[panel],
    }))
  }

  return (
    <section className="dashboard-panel price-chart-panel" aria-labelledby="price-chart-title">
      <div className="panel-header price-chart-header">
        <div>
          <p>{chart.intervalLabel ?? 'OHLCV'}</p>
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

      <div className="chart-toolbar">
        <div className="range-selector" aria-label="Chart time range">
          {chart.ranges.map((range) => {
            const isCustom = isCustomMarketDataRange(range)
            const isActive = activeRange === range
            return (
              <button
                className={`${isActive ? 'is-active' : ''} ${isCustom && isCustomRangeOpen ? 'is-editing' : ''}`.trim()}
                type="button"
                key={range}
                onClick={() => onRangeChange(range)}
                aria-pressed={isActive}
                aria-expanded={isCustom ? isCustomRangeOpen : undefined}
              >
                {range}
              </button>
            )
          })}
        </div>

        <label className="chart-interval-selector">
          <span>Interval</span>
          <select value={selectedInterval} onChange={(event) => onIntervalChange(event.target.value)}>
            {intervalOptions.map((option) => (
              <option value={option.value} key={option.value}>{option.label}</option>
            ))}
          </select>
        </label>

        <label className="chart-type-selector">
          <span>Chart</span>
          <select value={chartType} onChange={(event) => setChartType(event.target.value)}>
            {chartTypeOptions.map((option) => (
              <option value={option.value} key={option.value}>{option.label}</option>
            ))}
          </select>
        </label>

        <div className="indicator-toggle-group" aria-label="Chart indicators">
          {[
            ['volume', 'Volume'],
            ['macd', 'MACD'],
            ['rsi', 'RSI'],
          ].map(([panel, label]) => (
            <button
              className={visiblePanels[panel] ? 'is-active' : ''}
              type="button"
              key={panel}
              onClick={() => togglePanel(panel)}
              aria-pressed={visiblePanels[panel]}
            >
              {label}
            </button>
          ))}
        </div>

        <button
          className="chart-reset-button"
          type="button"
          onClick={resetVisibleWindow}
          disabled={isFullView}
        >
          Reset view
        </button>
      </div>

      {isCustomRangeOpen && (
        <div className="dashboard-custom-range" aria-label="Custom chart date range">
          <label>
            <span>Start date</span>
            <input
              type="date"
              value={customRange?.startDate ?? ''}
              max={customRangeMaxDate}
              onChange={(event) => onCustomRangeChange('startDate', event.target.value)}
            />
          </label>
          <label>
            <span>End date</span>
            <input
              type="date"
              value={customRange?.endDate ?? ''}
              max={customRangeMaxDate}
              onChange={(event) => onCustomRangeChange('endDate', event.target.value)}
            />
          </label>
          <label>
            <span>Interval</span>
            <select
              value={customRange?.interval ?? selectedInterval}
              onChange={(event) => onCustomRangeChange('interval', event.target.value)}
            >
              {intervalOptions.map((option) => (
                <option value={option.value} key={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <div className="custom-range-actions">
            <button className="is-secondary" type="button" onClick={onCustomRangeCancel}>Cancel</button>
            <button
              className="is-primary"
              type="button"
              onClick={onCustomRangeApply}
              disabled={Boolean(customRangeError)}
            >
              Apply
            </button>
          </div>
          {customRangeError && <span role="alert">{customRangeError}</span>}
        </div>
      )}

      {chart.isLoading ? (
        <ChartState>
          <strong>Loading {chart.intervalLabel ?? 'OHLCV'}...</strong>
          <span>Fetching Twelve Data candles through the Django API.</span>
        </ChartState>
      ) : chart.error ? (
        <ChartState>
          <strong>{chart.intervalLabel ?? 'OHLCV'} unavailable.</strong>
          <span>{chart.error}</span>
        </ChartState>
      ) : chart.isEmpty ? (
        <ChartState>
          <strong>No {chart.intervalLabel ?? 'OHLCV'} yet.</strong>
          <span>Try another range or refresh later.</span>
        </ChartState>
      ) : (
        <div
          ref={chartContainerRef}
          className={`price-chart is-${chartType} ${isDragging ? 'is-dragging' : ''}`.trim()}
          role="img"
          aria-label={`${chart.symbol} ${chart.intervalLabel ?? 'OHLCV'} multi-panel ${chartTypeOptions.find((option) => option.value === chartType)?.label ?? 'Candlestick'} chart for ${activeRange}`}
          onDoubleClick={resetVisibleWindow}
          onPointerCancel={handlePointerUp}
          onPointerDown={handlePointerDown}
          onPointerLeave={() => {
            if (!dragRef.current) setHoverState(null)
          }}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
        >
          <svg
            viewBox={`0 0 ${chartWidth} ${geometry.chartHeight}`}
            preserveAspectRatio="none"
            style={{ height: `${geometry.chartHeight}px` }}
          >
            {geometry.priceAxisValues.map((value, index) => {
              const y = geometry.panels.price.top + (index / 4) * geometry.panels.price.height
              const overlapsActivePrice = activePriceMarkerY !== null && Math.abs(y - activePriceMarkerY) < 13
              return (
                <g key={value}>
                  <line className="chart-grid-line" x1={padding.left} x2={geometry.plotRight} y1={y} y2={y} />
                  {!overlapsActivePrice && (
                    <text className="chart-axis-label" x={geometry.axisLabelX} y={y + 4}>
                      {formatAxisPrice(value)}
                    </text>
                  )}
                </g>
              )
            })}

            {Object.entries(geometry.panels).map(([panelName, panel]) => (
              <g key={`axis-${panelName}`}>
                <line
                  className="chart-axis-line"
                  x1={geometry.plotRight}
                  x2={geometry.plotRight}
                  y1={panel.top}
                  y2={panel.bottom}
                />
                <text className="chart-panel-label" x={padding.left} y={panel.top + 12}>
                  {panelName === 'price'
                    ? chartTypeOptions.find((option) => option.value === chartType)?.label ?? 'Candlestick'
                    : panelName.toUpperCase()}
                </text>
              </g>
            ))}

            {['volume', 'macd', 'rsi'].map((panel) => geometry.panels[panel] && (
              <line
                className="chart-panel-divider"
                x1={padding.left}
                x2={geometry.plotRight}
                y1={geometry.panels[panel].top - panelGap / 2}
                y2={geometry.panels[panel].top - panelGap / 2}
                key={panel}
              />
            ))}

            {isLineChart && geometry.lineAreaPath && (
              <path className="close-area" d={geometry.lineAreaPath} />
            )}

            {isLineChart && geometry.linePath && (
              <path className="close-line" d={geometry.linePath} />
            )}

            {geometry.items.map((item, index) => (
              <g className={`candle-item ${item.isUp ? 'is-up' : 'is-down'} ${hoverState?.index === index ? 'is-active' : ''}`} key={item.date}>
                {!isLineChart && (
                  <>
                    <line className="candle-wick" x1={item.x} x2={item.x} y1={item.highY} y2={item.lowY} />
                    <rect
                      className="candle-body"
                      x={item.x - geometry.candleWidth / 2}
                      y={item.bodyTop}
                      width={geometry.candleWidth}
                      height={item.bodyHeight}
                      rx="1"
                    />
                  </>
                )}
                {isLineChart && hoverState?.index === index && (
                  <circle className="close-point is-active" cx={item.x} cy={item.closeY} r="3.6" />
                )}
                {geometry.panels.volume && (
                  <rect
                    className="volume-bar"
                    x={item.x - geometry.candleWidth / 2}
                    y={item.volumeY}
                    width={geometry.candleWidth}
                    height={item.volumeHeight}
                    rx="1"
                  />
                )}
                {geometry.panels.macd && geometry.hasMacdData && Number.isFinite(item.histogramY) && (
                  <rect
                    className={`macd-histogram ${item.histogram >= 0 ? 'is-up' : 'is-down'}`}
                    x={item.x - geometry.candleWidth / 2}
                    y={Math.min(item.histogramY, item.histogramZeroY)}
                    width={geometry.candleWidth}
                    height={item.histogramHeight}
                    rx="1"
                  />
                )}
              </g>
            ))}

            {geometry.panels.macd && (
              <>
                {geometry.hasMacdData ? (
                  <>
                    <line
                      className="indicator-reference-line"
                      x1={padding.left}
                      x2={geometry.plotRight}
                      y1={geometry.items[0]?.histogramZeroY ?? geometry.panels.macd.bottom}
                      y2={geometry.items[0]?.histogramZeroY ?? geometry.panels.macd.bottom}
                    />
                    <path className="macd-line" d={geometry.macdLinePath} />
                    <path className="macd-signal-line" d={geometry.signalLinePath} />
                  </>
                ) : (
                  <text className="indicator-warning" x={padding.left} y={geometry.panels.macd.top + geometry.panels.macd.height / 2}>
                    {indicatorWarnings.macd || 'Insufficient historical data for MACD.'}
                  </text>
                )}
              </>
            )}

            {geometry.panels.rsi && (
              <>
                {[70, 30].map((level) => {
                  const y = geometry.panels.rsi.top + ((100 - level) / 100) * geometry.panels.rsi.height
                  return (
                    <line
                      className="indicator-reference-line"
                      x1={padding.left}
                      x2={geometry.plotRight}
                      y1={y}
                      y2={y}
                      key={level}
                    />
                  )
                })}
                {geometry.hasRsiData ? (
                  <path className="rsi-line" d={geometry.rsiLinePath} />
                ) : (
                  <text className="indicator-warning" x={padding.left} y={geometry.panels.rsi.top + geometry.panels.rsi.height / 2}>
                    {indicatorWarnings.rsi || 'Insufficient historical data for RSI.'}
                  </text>
                )}
              </>
            )}

            {geometry.panels.volume && (
              <g className="chart-panel-axis" aria-hidden="true">
                {geometry.volumeAxisItems.map((tick) => (
                  <text className="chart-axis-label" x={geometry.axisLabelX} y={tick.y} key={`volume-${tick.value}`}>
                    {formatCompactVolume(tick.value)}
                  </text>
                ))}
                {activeItem && (
                  <text className="chart-panel-value" x={padding.left + 52} y={geometry.panels.volume.top + 12}>
                    Vol {formatCompactVolume(activeItem.volume)}
                  </text>
                )}
              </g>
            )}

            {geometry.panels.macd && (
              <g className="chart-panel-axis" aria-hidden="true">
                {geometry.macdAxisItems.map((tick) => (
                  <text className="chart-axis-label" x={geometry.axisLabelX} y={tick.y + 4} key={`macd-${tick.value}`}>
                    {formatIndicatorValue(tick.value)}
                  </text>
                ))}
                {geometry.hasMacdData && activeItem && (
                  <g className="indicator-legend" transform={`translate(${padding.left + 48} ${geometry.panels.macd.top + 12})`}>
                    <text className="indicator-legend-item is-macd" x="0" y="0">
                      MACD {formatIndicatorValue(activeItem.macd)}
                    </text>
                    <text className="indicator-legend-item is-signal" x="78" y="0">
                      Signal {formatIndicatorValue(activeItem.signal)}
                    </text>
                    <text className="indicator-legend-item is-histogram" x="166" y="0">
                      Hist {formatIndicatorValue(activeItem.histogram)}
                    </text>
                  </g>
                )}
              </g>
            )}

            {geometry.panels.rsi && (
              <g className="chart-panel-axis" aria-hidden="true">
                {geometry.rsiAxisItems.map((tick) => (
                  <text className="chart-axis-label" x={geometry.axisLabelX} y={tick.y + 4} key={`rsi-${tick.value}`}>
                    {tick.value}
                  </text>
                ))}
                {geometry.hasRsiData && activeItem && (
                  <text className="chart-panel-value is-rsi" x={padding.left + 48} y={geometry.panels.rsi.top + 12}>
                    RSI {formatIndicatorValue(activeItem.rsi, 1)}
                  </text>
                )}
              </g>
            )}

            {activeItem && activePriceMarkerY !== null && (
              <g className="chart-price-marker" aria-hidden="true">
                <line
                  className="latest-price-line"
                  x1={padding.left}
                  x2={geometry.plotRight}
                  y1={activeItem.closeY}
                  y2={activeItem.closeY}
                />
                <rect
                  x={geometry.plotRight + 4}
                  y={activePriceMarkerY - 9}
                  width="62"
                  height="18"
                  rx="5"
                />
                <text x={geometry.axisLabelX} y={activePriceMarkerY + 4}>
                  {activeItem.close.toFixed(2)}
                </text>
              </g>
            )}

            {hoveredItem && (
              <g className="chart-crosshair" aria-hidden="true">
                <line
                  className="chart-crosshair-vertical"
                  x1={hoveredItem.x}
                  x2={hoveredItem.x}
                  y1={padding.top}
                  y2={geometry.chartHeight - padding.bottom}
                />
                <line
                  className="chart-crosshair-horizontal"
                  x1={padding.left}
                  x2={geometry.plotRight}
                  y1={hoveredItem.closeY}
                  y2={hoveredItem.closeY}
                />
              </g>
            )}

            {geometry.labelIndexes.map((index) => {
              const item = geometry.items[index]
              const label = chart.labels[index + normalizedWindow.start] ?? item.date
              const textAnchor = index === 0 ? 'start' : index === geometry.items.length - 1 ? 'end' : 'middle'
              return (
                <text
                  className="chart-x-label"
                  x={item.x}
                  y={geometry.chartHeight - 8}
                  textAnchor={textAnchor}
                  key={`${item.date}-${index}`}
                >
                  {label}
                </text>
              )
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
