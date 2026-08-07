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

const rangePatterns = {
  '1D': [-1.05, -0.86, -0.93, -0.62, -0.71, -0.48, -0.55, -0.19, -0.31, -0.06, -0.18, 0.12, 0.02, 0.34, 0.21, 0.45, 0.38, 0.67, 0.56, 0.72],
  '1W': [-2.3, -2.0, -2.15, -1.66, -1.42, -1.58, -1.11, -0.87, -1.02, -0.55, -0.72, -0.24, -0.08, -0.31, 0.16, 0.02, 0.38, 0.27, 0.61, 0.72],
  '1M': [-3.9, -3.35, -3.58, -2.9, -2.42, -2.65, -1.94, -2.18, -1.35, -1.7, -0.88, -0.54, -0.79, -0.12, -0.41, 0.15, 0.02, 0.44, 0.31, 0.72],
  '3M': [-5.7, -4.9, -5.35, -4.3, -3.65, -4.02, -2.88, -3.2, -2.1, -2.55, -1.42, -0.86, -1.2, -0.18, -0.72, 0.02, -0.25, 0.49, 0.18, 0.72],
  '6M': [-6.8, -5.9, -6.25, -4.95, -4.2, -4.62, -3.3, -3.72, -2.38, -2.82, -1.55, -0.92, -1.28, -0.2, -0.76, 0.08, -0.18, 0.53, 0.2, 0.72],
  '1Y': [1.6, 0.45, -1.2, -0.35, -2.1, -3.05, -2.4, -1.25, -1.88, -0.74, -1.45, -0.32, -0.86, 0.1, -0.57, 0.42, -0.08, 0.55, 0.22, 0.72],
}

const volumePattern = [1.28, 0.82, 0.94, 1.12, 0.76, 0.88, 1.05, 0.71, 0.97, 1.31, 0.85, 1.14, 0.79, 0.92, 1.21, 0.74, 1.09, 0.83, 1.18, 1.36]

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

const intervalPriceScale = {
  '30m': 0.74,
  '1H': 0.86,
  '1D': 1,
  '1W': 1.14,
  '1M': 1.28,
}

const intervalVolumeScale = {
  '30m': 0.48,
  '1H': 0.68,
  '1D': 1,
  '1W': 1.38,
  '1M': 1.72,
}

function expandPattern(pattern, count = 36) {
  return Array.from({ length: count }, (_, index) => {
    const position = (index / (count - 1)) * (pattern.length - 1)
    const leftIndex = Math.floor(position)
    const rightIndex = Math.min(leftIndex + 1, pattern.length - 1)
    const fraction = position - leftIndex
    const interpolated = pattern[leftIndex] + (pattern[rightIndex] - pattern[leftIndex]) * fraction
    return interpolated + Math.sin(index * 1.83) * 0.075
  })
}

function createHistory(basePrice, swing, baseVolume) {
  return Object.fromEntries(
    marketPresetRanges.map((range, rangeIndex) => [
      range,
      Object.fromEntries(
        marketBarIntervals.map((interval, intervalIndex) => {
          const priceScale = intervalPriceScale[interval]
          const expandedPattern = expandPattern(rangePatterns[range])
          const timestamps = createRangeTimestamps(range, expandedPattern.length)
          let closes = expandedPattern.map((movement, index) => {
            const waveOffset = index + rangeIndex * 1.7 + intervalIndex * 0.9
            const secondaryWave = Math.sin(waveOffset * 1.37) * swing * 0.12 * priceScale
            return Number((basePrice + movement * swing * priceScale + secondaryWave).toFixed(2))
          })

          const closingAdjustment = basePrice - closes.at(-1)
          closes = closes.map((close) => Number((close + closingAdjustment).toFixed(2)))
          const candleScale = Math.max(Math.abs(swing) * priceScale, 0.5)
          const opens = closes.map((close, index) => {
            const reference = index === 0 ? close - candleScale * 0.18 : closes[index - 1]
            return Number((reference + Math.sin((index + intervalIndex + 1) * 1.19) * candleScale * 0.075).toFixed(2))
          })
          const highs = closes.map((close, index) => {
            const wick = candleScale * (0.14 + ((index % 5) + 1) * 0.025)
            return Number((Math.max(opens[index], close) + wick).toFixed(2))
          })
          const lows = closes.map((close, index) => {
            const wick = candleScale * (0.13 + (((index + 2) % 5) + 1) * 0.024)
            return Number((Math.min(opens[index], close) - wick).toFixed(2))
          })

          const volumes = closes.map((_, index) =>
            Math.round(
              baseVolume *
              intervalVolumeScale[interval] *
              volumePattern[index % volumePattern.length] *
              (1 + rangeIndex * 0.1) *
              (1 + Math.cos(index * 0.73) * 0.08),
            ),
          )
          const candles = closes.map((close, index) => ({
            id: `${range}-${interval}-${index}`,
            timestamp: timestamps[index],
            open: opens[index],
            high: highs[index],
            low: lows[index],
            close,
            volume: volumes[index],
          }))

          return [interval, { candles, opens, highs, lows, closes, volumes, labels: rangeLabels[range] }]
        }),
      ),
    ]),
  )
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

export const marketAnalysisStocks = [
  {
    symbol: 'AAPL',
    company: 'Apple Inc.',
    exchange: 'NASDAQ',
    price: 189.84,
    formattedPrice: '$189.84',
    change: '+$2.41',
    percent: '+1.29%',
    direction: 'up',
    stats: { open: '$187.43', high: '$190.12', low: '$186.91', marketCap: '$2.91T' },
    indicators: {
      ma: { value: '$185.72', signal: 'Buy', tone: 'positive', period: '20 periods', description: 'Price remains above its short-term moving average, supporting the current upward trend.' },
      ema: { value: '$187.16', signal: 'Buy', tone: 'positive', period: '20 periods', description: 'The faster EMA is rising and remains below the latest price, indicating positive momentum.' },
      bollinger: { value: '$181.20 – $192.46', signal: 'Neutral', tone: 'neutral', period: '20 / 2σ', description: 'Price is trading in the upper half of the band without reaching an overextended level.' },
      macd: { period: '12 / 26 / 9' },
      rsi: { period: '14 periods' },
    },
    history: createHistory(189.84, 1.55, 5120000),
  },
  {
    symbol: 'MSFT',
    company: 'Microsoft Corp.',
    exchange: 'NASDAQ',
    price: 449.52,
    formattedPrice: '$449.52',
    change: '+$2.86',
    percent: '+0.64%',
    direction: 'up',
    stats: { open: '$446.91', high: '$451.06', low: '$445.82', marketCap: '$3.34T' },
    indicators: {
      ma: { value: '$441.83', signal: 'Buy', tone: 'positive', period: '20 periods', description: 'The share price is holding comfortably above its 20-period mean.' },
      ema: { value: '$445.28', signal: 'Buy', tone: 'positive', period: '20 periods', description: 'The EMA slope remains positive with steady short-term price momentum.' },
      bollinger: { value: '$430.44 – $454.18', signal: 'Watch', tone: 'warning', period: '20 / 2σ', description: 'Price is approaching the upper band, suggesting momentum with limited near-term room.' },
      macd: { period: '12 / 26 / 9' },
      rsi: { period: '14 periods' },
    },
    history: createHistory(449.52, 2.6, 3860000),
  },
  {
    symbol: 'NVDA',
    company: 'NVIDIA Corp.',
    exchange: 'NASDAQ',
    price: 131.88,
    formattedPrice: '$131.88',
    change: '+$3.52',
    percent: '+2.74%',
    direction: 'up',
    stats: { open: '$128.74', high: '$132.45', low: '$127.96', marketCap: '$3.24T' },
    indicators: {
      ma: { value: '$126.31', signal: 'Buy', tone: 'positive', period: '20 periods', description: 'Price acceleration keeps the stock well above its short-term average.' },
      ema: { value: '$128.47', signal: 'Buy', tone: 'positive', period: '20 periods', description: 'The EMA is rising rapidly and confirms recent price strength.' },
      bollinger: { value: '$118.92 – $134.70', signal: 'Watch', tone: 'warning', period: '20 / 2σ', description: 'Price is near the upper volatility band after a strong advance.' },
      macd: { period: '12 / 26 / 9' },
      rsi: { period: '14 periods' },
    },
    history: createHistory(131.88, 1.75, 10400000),
  },
  {
    symbol: 'TSLA',
    company: 'Tesla Inc.',
    exchange: 'NASDAQ',
    price: 248.23,
    formattedPrice: '$248.23',
    change: '-$2.96',
    percent: '-1.18%',
    direction: 'down',
    stats: { open: '$251.18', high: '$252.42', low: '$246.80', marketCap: '$791.8B' },
    indicators: {
      ma: { value: '$252.80', signal: 'Sell', tone: 'negative', period: '20 periods', description: 'Price has slipped below its short-term mean, weakening the immediate trend.' },
      ema: { value: '$250.91', signal: 'Sell', tone: 'negative', period: '20 periods', description: 'The latest price is below the EMA and short-term momentum has turned lower.' },
      bollinger: { value: '$238.12 – $265.44', signal: 'Neutral', tone: 'neutral', period: '20 / 2σ', description: 'Price remains near the middle of a relatively wide volatility channel.' },
      macd: { period: '12 / 26 / 9' },
      rsi: { period: '14 periods' },
    },
    history: createHistory(248.23, -1.9, 7820000),
  },
  {
    symbol: 'AMZN',
    company: 'Amazon.com Inc.',
    exchange: 'NASDAQ',
    price: 199.34,
    formattedPrice: '$199.34',
    change: '+$2.77',
    percent: '+1.41%',
    direction: 'up',
    stats: { open: '$196.88', high: '$200.21', low: '$196.42', marketCap: '$2.09T' },
    indicators: {
      ma: { value: '$195.84', signal: 'Above', tone: 'positive', period: '20 periods', description: 'Price remains above its short-term moving average with steady upward momentum.' },
      ema: { value: '$197.12', signal: 'Above', tone: 'positive', period: '20 periods', description: 'The latest price is holding above the 20-period EMA.' },
      bollinger: { value: '$190.26 - $201.48', signal: 'Neutral', tone: 'neutral', period: '20 / 2 sigma', description: 'Price remains inside the upper half of the current volatility range.' },
      macd: { period: '12 / 26 / 9' },
      rsi: { period: '14 periods' },
    },
    history: createHistory(199.34, 1.4, 4960000),
  },
  {
    symbol: 'GOOGL',
    company: 'Alphabet Inc.',
    exchange: 'NASDAQ',
    price: 191.18,
    formattedPrice: '$191.18',
    change: '-$0.61',
    percent: '-0.32%',
    direction: 'down',
    stats: { open: '$191.96', high: '$192.64', low: '$190.42', marketCap: '$2.36T' },
    indicators: {
      ma: { value: '$193.08', signal: 'Below', tone: 'negative', period: '20 periods', description: 'Price is trading slightly below its short-term moving average.' },
      ema: { value: '$192.42', signal: 'Below', tone: 'negative', period: '20 periods', description: 'The latest price remains below the 20-period EMA.' },
      bollinger: { value: '$187.74 - $198.42', signal: 'Neutral', tone: 'neutral', period: '20 / 2 sigma', description: 'Price is trading within the lower half of the current volatility range.' },
      macd: { period: '12 / 26 / 9' },
      rsi: { period: '14 periods' },
    },
    history: createHistory(191.18, -1.15, 4210000),
  },
  {
    symbol: 'META',
    company: 'Meta Platforms Inc.',
    exchange: 'NASDAQ',
    price: 507.42,
    formattedPrice: '$507.42',
    change: '+$3.78',
    percent: '+0.75%',
    direction: 'up',
    stats: { open: '$503.82', high: '$509.16', low: '$502.94', marketCap: '$1.28T' },
    indicators: {
      ma: { value: '$504.66', signal: 'Above', tone: 'positive', period: '20 periods', description: 'Price is modestly above its short-term moving average.' },
      ema: { value: '$505.21', signal: 'Above', tone: 'positive', period: '20 periods', description: 'The latest price is holding just above the 20-period EMA.' },
      bollinger: { value: '$496.84 - $514.26', signal: 'Neutral', tone: 'neutral', period: '20 / 2 sigma', description: 'Price is near the center of the current volatility range.' },
      macd: { period: '12 / 26 / 9' },
      rsi: { period: '14 periods' },
    },
    history: createHistory(507.42, 0.72, 3380000),
  },
  {
    symbol: 'SPY',
    company: 'SPDR S&P 500 ETF',
    exchange: 'NYSE Arca',
    price: 562.21,
    formattedPrice: '$562.21',
    change: '+$0.98',
    percent: '+0.17%',
    direction: 'up',
    stats: { open: '$561.16', high: '$563.04', low: '$560.72', marketCap: '$516.4B' },
    indicators: {
      ma: { value: '$558.74', signal: 'Above', tone: 'positive', period: '20 periods', description: 'The ETF remains above its short-term moving average.' },
      ema: { value: '$560.18', signal: 'Above', tone: 'positive', period: '20 periods', description: 'Price is holding modestly above the 20-period EMA.' },
      bollinger: { value: '$551.62 - $565.86', signal: 'Neutral', tone: 'neutral', period: '20 / 2 sigma', description: 'Price remains within the upper half of the current volatility range.' },
      macd: { period: '12 / 26 / 9' },
      rsi: { period: '14 periods' },
    },
    history: createHistory(562.21, 1.25, 6840000),
  },
]
