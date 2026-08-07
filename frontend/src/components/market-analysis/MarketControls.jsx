import { useRef, useState } from 'react'

function formatDateInput(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function createDefaultDates() {
  const end = new Date()
  const start = new Date(end.getFullYear(), end.getMonth(), end.getDate() - 30)
  return { startDate: formatDateInput(start), endDate: formatDateInput(end) }
}

function validateCustomDates(dates, today) {
  if (!dates.startDate || !dates.endDate) return 'Please select both Start Date and End Date.'
  if (dates.startDate > dates.endDate) return 'Start Date cannot be later than End Date.'
  if (dates.endDate > today) return 'End Date cannot be later than today.'
  return ''
}

function getIntervalValue(interval) {
  return typeof interval === 'string' ? interval : interval.value
}

function getIntervalLabel(interval) {
  return typeof interval === 'string' ? interval : interval.label
}

const chartTypeOptions = [
  { label: 'Candlestick', value: 'candlestick' },
  { label: 'Line', value: 'line' },
]

export default function MarketControls({
  stocks,
  selectedSymbol,
  onStockChange,
  ranges,
  selectedRange,
  onRangeChange,
  intervals,
  selectedInterval,
  onIntervalChange,
  chartType,
  onChartTypeChange,
  customRange,
  onApplyCustomRange,
  dataStatusLabel = 'Market Data API',
  dataStatusDetail = 'Twelve Data OHLCV via Django',
}) {
  const [isCustomOpen, setIsCustomOpen] = useState(false)
  const [draftDates, setDraftDates] = useState(() => customRange ?? createDefaultDates())
  const draftDatesRef = useRef(draftDates)
  const startDateInputRef = useRef(null)
  const endDateInputRef = useRef(null)
  const [customError, setCustomError] = useState('')
  const today = formatDateInput(new Date())

  const openCustomRange = () => {
    const nextDates = customRange ?? createDefaultDates()
    draftDatesRef.current = nextDates
    setDraftDates(nextDates)
    setCustomError('')
    setIsCustomOpen(true)
  }

  const handleRangeClick = (range) => {
    if (range === 'Custom') {
      openCustomRange()
      return
    }

    setIsCustomOpen(false)
    setCustomError('')
    onRangeChange(range)
  }

  const updateDraftDate = (field, value) => {
    const nextDates = { ...draftDatesRef.current, [field]: value }
    draftDatesRef.current = nextDates
    setDraftDates(nextDates)
    setCustomError('')
  }

  const cancelCustomRange = () => {
    const nextDates = customRange ?? createDefaultDates()
    draftDatesRef.current = nextDates
    setDraftDates(nextDates)
    setCustomError('')
    setIsCustomOpen(false)
  }

  const applyCustomRange = () => {
    const latestDates = {
      startDate: startDateInputRef.current?.value ?? draftDatesRef.current.startDate,
      endDate: endDateInputRef.current?.value ?? draftDatesRef.current.endDate,
    }
    draftDatesRef.current = latestDates
    const validationError = validateCustomDates(latestDates, today)
    if (validationError) {
      setCustomError(validationError)
      return
    }

    onApplyCustomRange({ ...latestDates })
    setCustomError('')
    setIsCustomOpen(false)
  }

  return (
    <section className="market-controls" aria-label="Market analysis controls">
      <div className="market-controls-heading">
        <div className="market-controls-copy">
          <p>Equity research</p>
          <h2>Analyze price action and technical signals</h2>
        </div>
        <div className="market-data-status" aria-label={`${dataStatusLabel}, ${dataStatusDetail}`}>
          <strong>{dataStatusLabel}</strong>
          <span>{dataStatusDetail}</span>
        </div>
      </div>

      <div className="market-control-fields">
        <label className="stock-selector">
          <span>Stock</span>
          <select
            value={selectedSymbol}
            onChange={(event) => onStockChange(event.target.value)}
            disabled={!stocks.length}
          >
            {stocks.map((stock) => (
              <option value={stock.symbol} key={stock.symbol}>{stock.symbol} - {stock.company}</option>
            ))}
          </select>
        </label>

        <div className="market-range-control">
          <span>Time range</span>
          <div role="radiogroup" aria-label="Time range">
            {ranges.map((range) => {
              const isActive = selectedRange === range
              const isCustom = range === 'Custom'
              return (
                <button
                  className={`${isActive ? 'is-active' : ''} ${isCustom && isCustomOpen ? 'is-editing' : ''}`.trim()}
                  type="button"
                  key={range}
                  onClick={() => handleRangeClick(range)}
                  aria-pressed={isActive}
                  role="radio"
                  aria-checked={isActive}
                  aria-expanded={isCustom ? isCustomOpen : undefined}
                  aria-controls={isCustom ? 'custom-date-panel' : undefined}
                >
                  {range}
                </button>
              )
            })}
          </div>
          {selectedRange === 'Custom' && customRange && (
            <output className="active-custom-range">
              {customRange.startDate} - {customRange.endDate}
            </output>
          )}
        </div>

        <label className="bar-interval-control">
          <span>Bar interval</span>
          <select value={selectedInterval} onChange={(event) => onIntervalChange(event.target.value)}>
            {intervals.map((interval) => {
              const value = getIntervalValue(interval)
              return <option value={value} key={value}>{getIntervalLabel(interval)}</option>
            })}
          </select>
        </label>

        <label className="chart-type-control">
          <span>Chart type</span>
          <select value={chartType} onChange={(event) => onChartTypeChange(event.target.value)}>
            {chartTypeOptions.map((option) => (
              <option value={option.value} key={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
      </div>

      {isCustomOpen && (
        <div className="custom-date-panel" id="custom-date-panel" aria-label="Custom date range">
          <div className="custom-date-copy">
            <strong>Custom time range</strong>
          </div>

          <div className="custom-date-fields">
            <label>
              <span>Start Date</span>
              <input
                ref={startDateInputRef}
                type="date"
                value={draftDates.startDate}
                max={draftDates.endDate || today}
                onChange={(event) => updateDraftDate('startDate', event.target.value)}
                aria-invalid={Boolean(customError)}
              />
            </label>
            <label>
              <span>End Date</span>
              <input
                ref={endDateInputRef}
                type="date"
                value={draftDates.endDate}
                min={draftDates.startDate}
                max={today}
                onChange={(event) => updateDraftDate('endDate', event.target.value)}
                aria-invalid={Boolean(customError)}
              />
            </label>
          </div>

          <div className="custom-date-actions">
            <button className="is-secondary" type="button" onClick={cancelCustomRange}>Cancel</button>
            <button className="is-primary" type="button" onClick={applyCustomRange}>Apply</button>
          </div>

          {customError && <p className="custom-date-error" role="alert">{customError}</p>}
        </div>
      )}
    </section>
  )
}
