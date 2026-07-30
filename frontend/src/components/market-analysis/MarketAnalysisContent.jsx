import { useMemo, useState } from 'react'
import { getMarketHistory } from '../../data/marketAnalysisData'
import IndicatorOverlayControls from './IndicatorOverlayControls'
import MacdChart from './MacdChart'
import MarketControls from './MarketControls'
import MarketPriceChart from './MarketPriceChart'
import RsiChart from './RsiChart'
import TechnicalSummary from './TechnicalSummary'
import VolumeChart from './VolumeChart'

const dayInMilliseconds = 86400000

function parseIsoDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? '')
  if (!match) return null

  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const timestamp = Date.UTC(year, month - 1, day)
  const date = new Date(timestamp)

  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) return null

  return timestamp
}

function addUtcMonthsClamped(timestamp, months) {
  const date = new Date(timestamp)
  const firstOfTargetMonth = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + months, 1))
  const lastDayOfTargetMonth = new Date(Date.UTC(
    firstOfTargetMonth.getUTCFullYear(),
    firstOfTargetMonth.getUTCMonth() + 1,
    0,
  )).getUTCDate()

  return Date.UTC(
    firstOfTargetMonth.getUTCFullYear(),
    firstOfTargetMonth.getUTCMonth(),
    Math.min(date.getUTCDate(), lastDayOfTargetMonth),
  )
}

export function getCustomDefaultInterval(startDate, endDate) {
  const start = parseIsoDate(startDate)
  const end = parseIsoDate(endDate)
  if (!Number.isFinite(start) || !Number.isFinite(end) || start > end) return '1D'

  const spanDays = (end - start) / dayInMilliseconds
  if (spanDays <= 2) return '30m'
  if (spanDays <= 14) return '1H'
  if (end <= addUtcMonthsClamped(start, 6)) return '1D'
  if (end <= addUtcMonthsClamped(start, 24)) return '1W'
  return '1M'
}

export default function MarketAnalysisContent({
  stocks,
  ranges,
  intervals,
  defaultIntervals,
  overlayOptions,
  selectedSymbol,
  onSelectedSymbolChange,
}) {
  const [selectedRange, setSelectedRange] = useState('1D')
  const [selectedInterval, setSelectedInterval] = useState(defaultIntervals['1D'])
  const [customRange, setCustomRange] = useState(null)
  const [selectedOverlays, setSelectedOverlays] = useState(['ma5', 'ma10', 'ma20'])

  const selectedStock = useMemo(
    () => stocks.find((stock) => stock.symbol === selectedSymbol) ?? stocks[0],
    [selectedSymbol, stocks],
  )

  const chartSelection = useMemo(() => ({
    symbol: selectedStock.symbol,
    range: selectedRange,
    interval: selectedInterval,
    customRange: selectedRange === 'Custom' ? customRange : null,
  }), [customRange, selectedInterval, selectedRange, selectedStock.symbol])

  const selectedHistory = useMemo(
    () => getMarketHistory(selectedStock, chartSelection),
    [chartSelection, selectedStock],
  )

  const rangeLabel = selectedRange === 'Custom' && customRange
    ? `${customRange.startDate} – ${customRange.endDate}`
    : selectedRange
  const chartTimeframeLabel = `${rangeLabel} · ${selectedInterval} bars`

  const handleRangeChange = (nextRange) => {
    if (nextRange === selectedRange) return
    setSelectedRange(nextRange)
    setSelectedInterval(defaultIntervals[nextRange] ?? selectedInterval)
  }

  const handleCustomRangeApply = (dates) => {
    setCustomRange(dates)
    setSelectedRange('Custom')
    setSelectedInterval(getCustomDefaultInterval(dates.startDate, dates.endDate))
  }

  const toggleOverlay = (overlayId) => {
    setSelectedOverlays((current) =>
      current.includes(overlayId)
        ? current.filter((id) => id !== overlayId)
        : [...current, overlayId],
    )
  }

  return (
    <main
      className="main-content market-analysis-main"
      data-chart-range={selectedRange}
      data-chart-interval={selectedInterval}
      data-chart-start={selectedRange === 'Custom' ? customRange?.startDate : undefined}
      data-chart-end={selectedRange === 'Custom' ? customRange?.endDate : undefined}
    >
      <MarketControls
        stocks={stocks}
        selectedSymbol={selectedStock.symbol}
        onStockChange={onSelectedSymbolChange}
        ranges={ranges}
        selectedRange={selectedRange}
        onRangeChange={handleRangeChange}
        intervals={intervals}
        selectedInterval={selectedInterval}
        onIntervalChange={setSelectedInterval}
        customRange={customRange}
        onApplyCustomRange={handleCustomRangeApply}
      />

      <div className="market-analysis-grid">
        <MarketPriceChart
          stock={selectedStock}
          history={selectedHistory}
          rangeLabel={rangeLabel}
          interval={selectedInterval}
          overlayOptions={overlayOptions}
          selectedOverlays={selectedOverlays}
        />
        <IndicatorOverlayControls
          history={selectedHistory}
          options={overlayOptions}
          selectedOverlays={selectedOverlays}
          onToggle={toggleOverlay}
        />
        <RsiChart stock={selectedStock} history={selectedHistory} timeframeLabel={chartTimeframeLabel} />
        <TechnicalSummary history={selectedHistory} />
        <VolumeChart stock={selectedStock} history={selectedHistory} rangeLabel={rangeLabel} interval={selectedInterval} />
        <MacdChart stock={selectedStock} history={selectedHistory} timeframeLabel={chartTimeframeLabel} />
      </div>
    </main>
  )
}
