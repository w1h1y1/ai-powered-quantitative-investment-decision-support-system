export const marketTimeRanges = ['1D', '1W', '1M', '3M', '6M', '1Y', 'Custom']

export const marketBarIntervals = ['30m', '1H', '1D', '1W', '1M']

export const marketDefaultIntervals = {
  '1D': '30m',
  '1W': '1H',
  '1M': '1D',
  '3M': '1D',
  '6M': '1D',
  '1Y': '1W',
}

const marketPresetRanges = marketTimeRanges.filter((range) => range !== 'Custom')

export const marketOverlayOptions = [
  { id: 'ma5', label: 'MA5', fullName: 'Moving Average 5', type: 'ma', period: 5 },
  { id: 'ma10', label: 'MA10', fullName: 'Moving Average 10', type: 'ma', period: 10 },
  { id: 'ma20', label: 'MA20', fullName: 'Moving Average 20', type: 'ma', period: 20 },
  { id: 'ema20', label: 'EMA20', fullName: 'Exponential Moving Average 20', type: 'ema', period: 20 },
  { id: 'bollinger20', label: 'Bollinger', legendLabel: 'Bollinger Bands (20, 2)', fullName: 'Bollinger Bands (20, 2)', type: 'bollinger', period: 20 },
]


const rangeLabels = {
  '1D': ['09:30', '11:00', '12:30', '14:00', '16:00'],
  '1W': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
  '1M': ['Jun 12', 'Jun 19', 'Jun 26', 'Jul 3', 'Jul 11'],
  '3M': ['Apr 12', 'May 1', 'May 24', 'Jun 16', 'Jul 11'],
  '6M': ['Feb', 'Mar', 'Apr', 'May', 'Jul'],
  '1Y': ['Aug 25', 'Nov 25', 'Feb 26', 'May 26', 'Jul 26'],
}

const demoEndTimestamp = Date.UTC(2026, 6, 12, 16, 0)
const rangeStartTimestamps = {
  '1D': Date.UTC(2026, 6, 12, 9, 30),
  '1W': demoEndTimestamp - 6 * 86400000,
  '1M': demoEndTimestamp - 30 * 86400000,
  '3M': demoEndTimestamp - 92 * 86400000,
  '6M': demoEndTimestamp - 181 * 86400000,
  '1Y': demoEndTimestamp - 365 * 86400000,
}

function createTimeline(startTimestamp, endTimestamp, count) {
  return Array.from({ length: count }, (_, index) => {
    if (count <= 1) return endTimestamp
    return Math.round(startTimestamp + ((endTimestamp - startTimestamp) * index) / (count - 1))
  })
}

function createRangeTimestamps(range, count) {
  return createTimeline(rangeStartTimestamps[range] ?? rangeStartTimestamps['1M'], demoEndTimestamp, count)
}


const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function parseDateValue(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? '')
  if (!match) return null
  const [, year, month, day] = match.map(Number)
  return Date.UTC(year, month - 1, day)
}

function formatCustomDate(timestamp, includeYear) {
  const date = new Date(timestamp)
  const year = String(date.getUTCFullYear()).slice(-2)
  const label = `${monthNames[date.getUTCMonth()]} ${date.getUTCDate()}`
  return includeYear ? `${label} '${year}` : label
}

function createCustomLabels(startDate, endDate) {
  const start = parseDateValue(startDate)
  const end = parseDateValue(endDate)
  if (!Number.isFinite(start) || !Number.isFinite(end) || start > end) return rangeLabels['1M']

  const includeYear = new Date(start).getUTCFullYear() !== new Date(end).getUTCFullYear()
  return Array.from({ length: 5 }, (_, index) => {
    const timestamp = start + ((end - start) * index) / 4
    return formatCustomDate(timestamp, includeYear)
  })
}

function createCustomTimestamps(startDate, endDate, count) {
  const start = parseDateValue(startDate)
  const end = parseDateValue(endDate)
  if (!Number.isFinite(start) || !Number.isFinite(end) || start > end) {
    return createRangeTimestamps('1M', count)
  }

  const marketOpen = start + 9.5 * 60 * 60 * 1000
  const marketClose = end + 16 * 60 * 60 * 1000
  return createTimeline(marketOpen, marketClose, count)
}

function getCustomSourceRange(startDate, endDate) {
  const start = parseDateValue(startDate)
  const end = parseDateValue(endDate)
  const spanDays = Number.isFinite(start) && Number.isFinite(end) ? (end - start) / 86400000 : 30

  if (spanDays <= 2) return '1D'
  if (spanDays <= 14) return '1W'
  if (spanDays <= 45) return '1M'
  if (spanDays <= 120) return '3M'
  if (spanDays <= 240) return '6M'
  return '1Y'
}

function parseFiniteNumber(value) {
  if (value === null || value === undefined || String(value).trim() === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function getCandleSortTime(candle) {
  const timestamp = parseFiniteNumber(candle?.timestamp)
  if (timestamp !== null) return timestamp

  const parsed = Date.parse(candle?.date ?? candle?.datetime ?? '')
  return Number.isFinite(parsed) ? parsed : null
}

function normalizeMarketHistory(history) {
  const candles = Array.isArray(history?.candles) ? history.candles : []
  const normalizedCandles = candles
    .map((candle, originalIndex) => {
      const sortTime = getCandleSortTime(candle)
      const open = parseFiniteNumber(candle?.open)
      const high = parseFiniteNumber(candle?.high)
      const low = parseFiniteNumber(candle?.low)
      const close = parseFiniteNumber(candle?.close)
      const volume = parseFiniteNumber(candle?.volume)
      if (
        sortTime === null
        || ![open, high, low, close].every(Number.isFinite)
        || high < low
      ) return null

      return {
        ...candle,
        open,
        high,
        low,
        close,
        volume: volume ?? 0,
        sortTime,
        originalIndex,
      }
    })
    .filter(Boolean)
    .sort((left, right) => left.sortTime - right.sortTime || left.originalIndex - right.originalIndex)
    .map(({ sortTime, originalIndex, ...candle }) => candle)

  return {
    ...history,
    candles: normalizedCandles,
    opens: normalizedCandles.map((candle) => candle.open),
    highs: normalizedCandles.map((candle) => candle.high),
    lows: normalizedCandles.map((candle) => candle.low),
    closes: normalizedCandles.map((candle) => candle.close),
    volumes: normalizedCandles.map((candle) => candle.volume),
  }
}

export function getMarketHistory(stock, { range, interval, customRange }) {
  const safeInterval = marketBarIntervals.includes(interval) ? interval : marketDefaultIntervals['1D']

  if (range !== 'Custom' || !customRange) {
    const safeRange = marketPresetRanges.includes(range) ? range : '1D'
    return normalizeMarketHistory(stock.history[safeRange][safeInterval])
  }

  const sourceRange = getCustomSourceRange(customRange.startDate, customRange.endDate)
  const source = stock.history[sourceRange][safeInterval]
  const customId = `${customRange.startDate}-${customRange.endDate}-${safeInterval}`
  const timestamps = createCustomTimestamps(customRange.startDate, customRange.endDate, source.candles.length)

  return normalizeMarketHistory({
    ...source,
    labels: createCustomLabels(customRange.startDate, customRange.endDate),
    candles: source.candles.map((candle, index) => ({
      ...candle,
      id: `Custom-${customId}-${index}`,
      timestamp: timestamps[index],
    })),
  })
}
