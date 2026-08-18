import {
  findLastFinite,
  macdSeries,
  movingAverageSeries,
  realizedVolatility,
  rsiSeries,
} from '../../utils/technicalIndicators.js'

export const dashboardSecurityStorageKey = 'aiquantification.dashboard.selectedSecurityId'

export const dashboardMarketDataRanges = ['1D', '1W', '1M', '3M', '6M', '1Y', '5Y', 'Custom']
export const dashboardMarketDataIntervals = [
  { label: '1m', value: '1min' },
  { label: '5m', value: '5min' },
  { label: '15m', value: '15min' },
  { label: '30m', value: '30min' },
  { label: '1h', value: '1h' },
  { label: '2h', value: '2h' },
  { label: '4h', value: '4h' },
  { label: '1D', value: '1day' },
  { label: '1W', value: '1week' },
]
export const dashboardDefaultIntervalsByRange = {
  '1D': '1min',
  '1W': '15min',
  '1M': '1h',
  '3M': '2h',
  '6M': '1day',
  '1Y': '1day',
  '5Y': '1week',
}
export const dashboardMarketDataMaxRequestPoints = 5000
export const dashboardMinimumVisibleCandles = 10

const intervalPointEstimatesPerDay = {
  '1min': 1440,
  '5min': 288,
  '15min': 96,
  '30min': 48,
  '1h': 24,
  '2h': 12,
  '4h': 6,
  '1day': 1,
  '1week': 1 / 7,
}

function clampNumber(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum)
}

function getDefaultStorage() {
  return typeof window === 'undefined' ? null : window.localStorage
}

function normalizeText(value) {
  return String(value ?? '').trim()
}

export function isSupportedMarketDataInterval(interval) {
  return dashboardMarketDataIntervals.some((option) => option.value === normalizeText(interval))
}

export function getDefaultMarketDataInterval(range) {
  return dashboardDefaultIntervalsByRange[normalizeText(range).toUpperCase()] ?? '1day'
}

export function normalizeSecurity(security) {
  if (!security) return null

  return {
    id: security.id,
    symbol: normalizeText(security.symbol).toUpperCase(),
    name: normalizeText(security.name),
    assetType: normalizeText(security.asset_type),
    exchange: normalizeText(security.exchange),
    currency: normalizeText(security.currency).toUpperCase(),
    micCode: normalizeText(security.mic_code ?? security.micCode).toUpperCase(),
    country: normalizeText(security.country),
    isActive: security.is_active === true,
  }
}

export function getActiveSecurities(response) {
  if (!Array.isArray(response)) return []

  return response
    .map(normalizeSecurity)
    .filter((security) => security?.id && security.symbol && security.name && security.isActive)
}

export function normalizeHoldingsToDashboardSecurities(response) {
  if (!Array.isArray(response)) return []

  const securitiesById = new Map()
  response.forEach((holding) => {
    const security = normalizeSecurity(holding?.security)
    if (!security?.id || !security.symbol || !security.name) return
    securitiesById.set(String(security.id), security)
  })

  return Array.from(securitiesById.values())
    .sort((left, right) => left.symbol.localeCompare(right.symbol))
}

export function upsertDashboardSecurity(securities, security) {
  if (!security?.id || !security.symbol || !security.isActive) return securities

  const nextSecurities = securities.filter(
    (currentSecurity) => String(currentSecurity.id) !== String(security.id),
  )
  return [...nextSecurities, security]
    .sort((left, right) => left.symbol.localeCompare(right.symbol))
}

export function filterSecurityOptions(securities, query) {
  const normalizedQuery = normalizeText(query).toLowerCase()
  if (!normalizedQuery) return securities

  return securities.filter((security) =>
    security.symbol.toLowerCase().includes(normalizedQuery)
    || security.name.toLowerCase().includes(normalizedQuery),
  )
}

export function resolveSelectedSecurityId({ securities, currentSecurityId, storedSecurityId }) {
  const validIds = new Set(securities.map((security) => String(security.id)))

  if (currentSecurityId && validIds.has(String(currentSecurityId))) {
    return String(currentSecurityId)
  }

  if (storedSecurityId && validIds.has(String(storedSecurityId))) {
    return String(storedSecurityId)
  }

  return securities[0] ? String(securities[0].id) : ''
}

export function readStoredSecurityId(storage = getDefaultStorage()) {
  if (!storage) return ''

  try {
    return storage.getItem(dashboardSecurityStorageKey) || ''
  } catch {
    return ''
  }
}

export function writeStoredSecurityId(securityId, storage = getDefaultStorage()) {
  if (!storage) return

  try {
    if (securityId) {
      storage.setItem(dashboardSecurityStorageKey, String(securityId))
    } else {
      storage.removeItem(dashboardSecurityStorageKey)
    }
  } catch {
    // Dashboard selection still works in React state when browser storage is unavailable.
  }
}

function parseMarketDataDate(value) {
  const rawValue = normalizeText(value)
  const match = rawValue.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T\s](\d{2}):(\d{2})(?::\d{2})?)?/)
  if (!match) return null

  const [, year, month, day, hour = '00', minute = '00'] = match
  const marketDate = `${year}-${month}-${day}`
  const marketMinute = Number(hour) * 60 + Number(minute)
  const parsedDate = new Date(Date.UTC(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
  ))
  if (Number.isNaN(parsedDate.getTime())) return null

  return {
    date: parsedDate,
    hasTime: match[4] !== undefined,
    marketDate,
    marketMinute,
    sortKey: match[4] === undefined ? marketDate : `${marketDate} ${hour}:${minute}`,
  }
}

export function formatDashboardDateLabel(value, interval = '1day', range = '') {
  const parsed = parseMarketDataDate(value)
  if (!parsed) return normalizeText(value)

  const normalizedInterval = normalizeText(interval).toLowerCase()
  const normalizedRange = normalizeText(range).toUpperCase()
  const isIntradayInterval = ['1min', '5min', '15min', '30min', '1h', '2h', '4h'].includes(normalizedInterval)
  if (isIntradayInterval && normalizedRange === '1D') {
    return new Intl.DateTimeFormat('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'UTC',
    }).format(parsed.date)
  }

  if (isIntradayInterval) {
    if (normalizedRange === '1W') {
      return new Intl.DateTimeFormat('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
        timeZone: 'UTC',
      }).format(parsed.date)
    }

    return new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
      timeZone: 'UTC',
    }).format(parsed.date)
  }

  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(parsed.date)
}

function parseNumber(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function padDatePart(value) {
  return String(value).padStart(2, '0')
}

function formatDateInputValue(value) {
  return [
    value.getFullYear(),
    padDatePart(value.getMonth() + 1),
    padDatePart(value.getDate()),
  ].join('-')
}

function subtractLocalMonths(value, months) {
  const targetMonthIndex = value.getMonth() - months
  const targetYear = value.getFullYear() + Math.floor(targetMonthIndex / 12)
  const targetMonth = ((targetMonthIndex % 12) + 12) % 12
  const daysInTargetMonth = new Date(targetYear, targetMonth + 1, 0).getDate()
  return new Date(targetYear, targetMonth, Math.min(value.getDate(), daysInTargetMonth))
}

function isValidDateInput(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value ?? ''))) return false
  const [year, month, day] = String(value).split('-').map(Number)
  const parsed = new Date(Date.UTC(year, month - 1, day))
  return parsed.getUTCFullYear() === year
    && parsed.getUTCMonth() === month - 1
    && parsed.getUTCDate() === day
}

function getDateSpanDays(startDate, endDate) {
  if (!isValidDateInput(startDate) || !isValidDateInput(endDate)) return null
  const [startYear, startMonth, startDay] = String(startDate).split('-').map(Number)
  const [endYear, endMonth, endDay] = String(endDate).split('-').map(Number)
  const startTime = Date.UTC(startYear, startMonth - 1, startDay)
  const endTime = Date.UTC(endYear, endMonth - 1, endDay)
  return Math.floor((endTime - startTime) / 86_400_000) + 1
}

export function estimateMarketDataPoints(startDate, endDate, interval) {
  const spanDays = getDateSpanDays(startDate, endDate)
  if (spanDays === null || !isSupportedMarketDataInterval(interval)) return null
  return spanDays * intervalPointEstimatesPerDay[interval]
}

export function getDefaultCustomMarketDataInterval(startDate, endDate) {
  const spanDays = getDateSpanDays(startDate, endDate)
  if (spanDays !== null && spanDays <= 2) return '1min'
  if (spanDays !== null && spanDays <= 8) return '15min'
  if (spanDays !== null && spanDays <= 32) return '1h'
  if (spanDays !== null && spanDays <= 93) return '2h'
  if (spanDays !== null && spanDays <= 366) return '1day'
  return '1week'
}

function formatCurrency(value, currency = 'USD') {
  if (!Number.isFinite(value)) return 'N/A'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

function formatSignedCurrency(value, currency) {
  if (!Number.isFinite(value)) return 'N/A'
  const sign = value >= 0 ? '+' : '-'
  return `${sign}${formatCurrency(Math.abs(value), currency)}`
}

function formatSignedPercent(value) {
  if (!Number.isFinite(value)) return 'N/A'
  const sign = value >= 0 ? '+' : '-'
  return `${sign}${Math.abs(value).toFixed(2)}%`
}

function formatCompactVolume(value) {
  if (!Number.isFinite(value)) return '0'
  return new Intl.NumberFormat('en-US', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

const marketSummaryColors = {
  SPY: '#6877f5',
  ONEQ: '#2bbf8a',
  DIA: '#ef6a78',
  'BTC/USD': '#f3a847',
}
const marketSummaryNames = {
  SPY: 'S&P 500 ETF proxy',
  ONEQ: 'NASDAQ Composite ETF proxy',
  DIA: 'Dow Jones Industrial Average ETF proxy',
  'BTC/USD': 'Bitcoin',
}
const dashboardMarketSummarySymbols = ['SPY', 'ONEQ', 'DIA', 'BTC/USD']

function isBitcoinSymbol(symbol) {
  return normalizeText(symbol).toUpperCase().includes('BTC')
}

function formatMarketSummaryPrice(value, symbol) {
  if (!Number.isFinite(value)) return 'Unavailable'
  if (isBitcoinSymbol(symbol)) {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: value >= 1000 ? 2 : 4,
    }).format(value)
  }

  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

function getMarketSummaryDirection(changeValue) {
  if (changeValue > 0) return 'up'
  if (changeValue < 0) return 'down'
  return 'neutral'
}

function formatMarketSummaryChange(value, symbol, direction) {
  if (!Number.isFinite(value)) return 'N/A'
  const sign = direction === 'up' ? '+' : direction === 'down' ? '-' : ''
  const absoluteValue = Math.abs(value)
  if (isBitcoinSymbol(symbol)) {
    return `${sign}${new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: absoluteValue >= 1000 ? 2 : 4,
    }).format(absoluteValue)}`
  }

  return `${sign}${absoluteValue.toFixed(2)}`
}

function formatMarketSummaryPercent(value, direction) {
  if (!Number.isFinite(value)) return 'N/A'
  const sign = direction === 'up' ? '+' : direction === 'down' ? '-' : ''
  return `${sign}${Math.abs(value).toFixed(2)}%`
}

function formatMarketSummaryUpdatedAt(value) {
  const parsed = parseMarketDataDate(value)
  if (!parsed) return ''

  const options = parsed.hasTime
    ? {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'UTC',
    }
    : {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      timeZone: 'UTC',
    }
  return new Intl.DateTimeFormat('en-US', options).format(parsed.date)
}

function parseNullableNumber(value) {
  if (value === null || value === undefined || String(value).trim() === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function normalizeMarketSummarySparkline(points) {
  if (!Array.isArray(points)) return []

  return points
    .map((point) => ({
      datetime: normalizeText(point?.datetime),
      close: parseNullableNumber(point?.close),
    }))
    .filter((point) => point.datetime && Number.isFinite(point.close))
}

function createUnavailableMarketSummaryCard(symbol, item = {}) {
  return {
    key: normalizeText(item?.key || item?.id || symbol),
    symbol,
    providerSymbol: normalizeText(item?.provider_symbol),
    name: normalizeText(item?.display_name) || marketSummaryNames[symbol] || symbol,
    latestPrice: null,
    previousClose: null,
    absoluteChange: null,
    percentageChange: null,
    value: 'Unavailable',
    change: 'Unavailable',
    percent: 'N/A',
    direction: 'neutral',
    color: marketSummaryColors[symbol] ?? '#6877f5',
    sparkline: [],
    updatedAt: normalizeText(item?.updated_at),
    dataStatus: 'unavailable',
    error: normalizeText(item?.error || item?.error_message || item?.provider_message) || 'Market data unavailable.',
  }
}

function normalizeMarketSummaryItem(item, symbol) {
  const latestPrice = parseNullableNumber(item?.latest_price)
  const previousClose = parseNullableNumber(item?.previous_close)
  const absoluteChange = parseNullableNumber(item?.absolute_change)
  const percentageChange = parseNullableNumber(item?.percentage_change)
  const sparkline = normalizeMarketSummarySparkline(item?.sparkline)
  const dataStatus = normalizeText(item?.data_status).toLowerCase()
  const isAvailable = dataStatus === 'ok'
    && Number.isFinite(latestPrice)
    && Number.isFinite(previousClose)
    && Number.isFinite(absoluteChange)
    && Number.isFinite(percentageChange)
    && sparkline.length > 1
  if (!isAvailable) return createUnavailableMarketSummaryCard(symbol, item)

  const direction = getMarketSummaryDirection(absoluteChange)
  return {
    key: normalizeText(item?.key || item?.id || symbol),
    symbol,
    providerSymbol: normalizeText(item?.provider_symbol),
    name: normalizeText(item?.display_name) || marketSummaryNames[symbol] || symbol,
    latestPrice,
    previousClose,
    absoluteChange,
    percentageChange,
    value: formatMarketSummaryPrice(latestPrice, symbol),
    change: formatMarketSummaryChange(absoluteChange, symbol, direction),
    percent: formatMarketSummaryPercent(percentageChange, direction),
    direction,
    color: marketSummaryColors[symbol] ?? '#6877f5',
    sparkline,
    updatedAt: normalizeText(item?.updated_at),
    dataStatus,
    error: normalizeText(item?.error),
  }
}

export function normalizeMarketSummary(response) {
  const rawItems = Array.isArray(response?.items) ? response.items : []
  const itemsBySymbol = new Map(rawItems.map((item) => [
    normalizeText(item?.symbol).toUpperCase(),
    item,
  ]))
  const items = dashboardMarketSummarySymbols.map((symbol) => {
    const item = itemsBySymbol.get(symbol)
    return item ? normalizeMarketSummaryItem(item, symbol) : createUnavailableMarketSummaryCard(symbol)
  })
  const formattedUpdatedAt = formatMarketSummaryUpdatedAt(response?.updated_at)

  return {
    items,
    source: normalizeText(response?.source),
    status: normalizeText(response?.status) || 'unavailable',
    cacheStatus: normalizeText(response?.cache_status || response?.metadata?.cache_status),
    generatedAt: normalizeText(response?.generated_at || response?.metadata?.generated_at),
    metadata: response?.metadata && typeof response.metadata === 'object' ? response.metadata : {},
    statusLabel: 'Latest Market Data',
    lastUpdatedLabel: formattedUpdatedAt ? `Last updated: ${formattedUpdatedAt}` : 'Last updated unavailable',
  }
}

export function getMarketSummaryDebugSummary(response, marketSummary) {
  return {
    response,
    renderedItems: (marketSummary?.items ?? []).map((item) => ({
      symbol: item.symbol,
      providerSymbol: item.providerSymbol,
      latestPrice: item.latestPrice,
      absoluteChange: item.absoluteChange,
      percentageChange: item.percentageChange,
      sparklineLastClose: item.sparkline.at(-1)?.close ?? null,
      updatedAt: item.updatedAt,
      dataStatus: item.dataStatus,
      error: item.error,
    })),
    metadata: marketSummary?.metadata ?? {},
    cacheStatus: marketSummary?.cacheStatus ?? '',
    generatedAt: marketSummary?.generatedAt ?? '',
  }
}

export function isCustomMarketDataRange(range) {
  return normalizeText(range).toUpperCase() === 'CUSTOM'
}

export function getTodayDateInputValue(now = new Date()) {
  return formatDateInputValue(now)
}

export function createDefaultCustomMarketDataRange(now = new Date()) {
  const endDate = formatDateInputValue(now)
  const startDate = formatDateInputValue(subtractLocalMonths(now, 1))
  return { startDate, endDate, interval: getDefaultCustomMarketDataInterval(startDate, endDate) }
}

export function validateCustomMarketDataRange(range, today = getTodayDateInputValue()) {
  const startDate = normalizeText(range?.startDate)
  const endDate = normalizeText(range?.endDate)
  const interval = normalizeText(range?.interval)

  if (!isValidDateInput(startDate) || !isValidDateInput(endDate)) {
    return 'Select valid start and end dates.'
  }
  if (startDate > endDate) {
    return 'Start date cannot be later than end date.'
  }
  if (startDate > today || endDate > today) {
    return 'Custom range cannot include future dates.'
  }
  if (!isSupportedMarketDataInterval(interval)) {
    return 'Select a supported interval.'
  }
  const estimatedPoints = estimateMarketDataPoints(startDate, endDate, interval)
  if (estimatedPoints > dashboardMarketDataMaxRequestPoints) {
    return 'This date range is too large for the selected interval. Choose a shorter date range or a larger interval.'
  }
  return ''
}

export function buildMarketDataRequestParams({ security, range, customRange, interval }) {
  const request = {
    securityId: security.id,
    range,
    interval,
  }

  if (isCustomMarketDataRange(range)) {
    request.startDate = customRange?.startDate
    request.endDate = customRange?.endDate
    request.interval = customRange?.interval ?? interval
  }

  return request
}

export function shouldApplyMarketDataResponse(activeRequestId, responseRequestId) {
  return activeRequestId === responseRequestId
}

function normalizeMarketDataRangeKey(range) {
  const normalized = normalizeText(range).toUpperCase()
  return normalized === 'CUSTOM' ? 'CUSTOM' : normalized
}

function getMarketDataResponseSecurityId(response) {
  return response?.security?.id ?? response?.metadata?.security_id ?? response?.security_id
}

function getMarketDataResponseRange(response) {
  return normalizeMarketDataRangeKey(response?.range ?? response?.metadata?.requested_range)
}

function getMarketDataResponseInterval(response) {
  return normalizeText(response?.interval ?? response?.metadata?.interval)
}

export function marketDataResponseMatchesRequest(response, request) {
  const responseSecurityId = getMarketDataResponseSecurityId(response)
  const requestSecurityId = request?.securityId
  if (!responseSecurityId || !requestSecurityId || String(responseSecurityId) !== String(requestSecurityId)) {
    return false
  }

  const responseRange = getMarketDataResponseRange(response)
  const requestRange = normalizeMarketDataRangeKey(request?.range)
  if (!responseRange || responseRange !== requestRange) {
    return false
  }

  const responseInterval = getMarketDataResponseInterval(response)
  const requestInterval = normalizeText(request?.interval)
  return Boolean(responseInterval && requestInterval && responseInterval === requestInterval)
}

export function normalizeDashboardVisibleWindow(window, total) {
  const safeTotal = Math.max(Math.floor(Number(total) || 0), 0)
  if (!safeTotal) return { start: 0, end: 0 }
  if (!window) return { start: 0, end: safeTotal - 1 }

  const rawStart = Number(window.start)
  const rawEnd = Number(window.end)
  const start = clampNumber(Number.isFinite(rawStart) ? Math.round(rawStart) : 0, 0, safeTotal - 1)
  const end = clampNumber(Number.isFinite(rawEnd) ? Math.round(rawEnd) : safeTotal - 1, 0, safeTotal - 1)

  return start <= end ? { start, end } : { start: end, end: start }
}

export function clampDashboardVisibleWindow(
  start,
  end,
  total,
  minimumVisibleCandles = dashboardMinimumVisibleCandles,
) {
  const safeTotal = Math.max(Math.floor(Number(total) || 0), 0)
  if (!safeTotal) return { start: 0, end: 0 }

  const safeMinimum = Math.max(1, Math.floor(Number(minimumVisibleCandles) || dashboardMinimumVisibleCandles))
  const minimumSize = Math.min(safeMinimum, safeTotal)
  const rawStart = Number(start)
  const rawEnd = Number(end)
  const rangeStart = Number.isFinite(rawStart) ? rawStart : 0
  const rangeEnd = Number.isFinite(rawEnd) ? rawEnd : safeTotal - 1
  const requestedStart = Math.min(rangeStart, rangeEnd)
  const requestedEnd = Math.max(rangeStart, rangeEnd)
  const requestedSize = Math.round(requestedEnd - requestedStart + 1)
  const size = clampNumber(requestedSize, minimumSize, safeTotal)
  const nextStart = clampNumber(Math.round(requestedStart), 0, safeTotal - size)

  return {
    start: nextStart,
    end: nextStart + size - 1,
  }
}

export function zoomDashboardVisibleWindow({
  window,
  total,
  anchorRatio,
  deltaY,
  minimumVisibleCandles = dashboardMinimumVisibleCandles,
}) {
  const safeTotal = Math.max(Math.floor(Number(total) || 0), 0)
  const current = normalizeDashboardVisibleWindow(window, safeTotal)
  if (!safeTotal || !Number.isFinite(deltaY) || deltaY === 0) return current

  const safeMinimum = Math.max(1, Math.floor(Number(minimumVisibleCandles) || dashboardMinimumVisibleCandles))
  const minimumSize = Math.min(safeMinimum, safeTotal)
  const currentSize = current.end - current.start + 1
  if (safeTotal <= minimumSize && currentSize === safeTotal) return current

  const nextSize = clampNumber(
    Math.round(currentSize * (deltaY > 0 ? 1.25 : 0.8)),
    minimumSize,
    safeTotal,
  )
  if (nextSize === currentSize) return current

  const safeAnchorRatio = clampNumber(Number(anchorRatio) || 0, 0, 1)
  const anchorIndex = current.start + safeAnchorRatio * (currentSize - 1)
  const nextStart = anchorIndex - safeAnchorRatio * (nextSize - 1)

  return clampDashboardVisibleWindow(nextStart, nextStart + nextSize - 1, safeTotal, safeMinimum)
}

export function panDashboardVisibleWindow({
  window,
  total,
  shift,
  minimumVisibleCandles = dashboardMinimumVisibleCandles,
}) {
  const safeTotal = Math.max(Math.floor(Number(total) || 0), 0)
  const current = normalizeDashboardVisibleWindow(window, safeTotal)
  const safeShift = Number(shift)
  if (!safeTotal || !Number.isFinite(safeShift) || safeShift === 0) return current
  if (current.start === 0 && current.end === safeTotal - 1) return current

  return clampDashboardVisibleWindow(
    current.start + safeShift,
    current.end + safeShift,
    safeTotal,
    minimumVisibleCandles,
  )
}

export function formatDashboardCandleTooltip(candle, currency = 'USD') {
  const open = parseNumber(candle?.open)
  const high = parseNumber(candle?.high)
  const low = parseNumber(candle?.low)
  const close = parseNumber(candle?.close)
  const change = close - open
  const changePercent = open ? (change / open) * 100 : null

  return {
    date: normalizeText(candle?.date),
    open: formatCurrency(open, currency),
    high: formatCurrency(high, currency),
    low: formatCurrency(low, currency),
    close: formatCurrency(close, currency),
    change: formatSignedCurrency(change, currency),
    changePercent: changePercent === null ? 'N/A' : formatSignedPercent(changePercent),
    volume: formatCompactVolume(parseNumber(candle?.volume)),
    tone: change > 0 ? 'up' : change < 0 ? 'down' : 'neutral',
  }
}

function isIntradayMarketDataInterval(interval) {
  return ['1min', '5min', '15min', '30min', '1h', '2h', '4h'].includes(normalizeText(interval).toLowerCase())
}

function isRegularTradingHoursTimestamp(parsedDate) {
  if (!parsedDate.hasTime) return true
  return parsedDate.marketMinute >= 570 && parsedDate.marketMinute <= 959
}

function normalizeMarketDataCandles(items, interval = '') {
  const candlesByTime = new Map()
  const shouldFilterRth = isIntradayMarketDataInterval(interval)

  items.forEach((item) => {
    const rawDate = normalizeText(item?.date ?? item?.datetime ?? item?.timestamp)
    const parsedDate = parseMarketDataDate(rawDate)
    if (!rawDate || !parsedDate) return
    if (shouldFilterRth && !isRegularTradingHoursTimestamp(parsedDate)) return

    const open = parseNullableNumber(item?.open)
    const high = parseNullableNumber(item?.high)
    const low = parseNullableNumber(item?.low)
    const close = parseNullableNumber(item?.close)
    if (![open, high, low, close].every(Number.isFinite) || high < low) return

    const candle = {
      date: rawDate,
      open,
      high,
      low,
      close,
      volume: parseNumber(item?.volume),
      marketDate: parsedDate.marketDate,
      marketMinute: parsedDate.hasTime ? parsedDate.marketMinute : null,
      sortKey: parsedDate.sortKey,
    }

    candlesByTime.set(parsedDate.sortKey, candle)
  })

  return Array.from(candlesByTime.values())
    .sort((left, right) => left.sortKey.localeCompare(right.sortKey))
    .map(({ marketDate, marketMinute, sortKey, ...candle }) => candle)
}

export function normalizeMarketData(response) {
  const values = Array.isArray(response?.values) ? response.values : []
  const warmupValues = Array.isArray(response?.warmup_values) ? response.warmup_values : []
  const interval = getMarketDataResponseInterval(response)
  const visibleData = normalizeMarketDataCandles(values, interval)
  const warmupCandles = normalizeMarketDataCandles(warmupValues, interval)
  const fullData = normalizeMarketDataCandles([...warmupValues, ...values], interval)
  const security = normalizeSecurity(response?.security)
  const metadata = response?.metadata && typeof response.metadata === 'object' ? response.metadata : {}

  return {
    security,
    range: getMarketDataResponseRange(response),
    interval,
    source: response?.source,
    isStale: response?.is_stale === true,
    metadata: {
      securityId: security?.id ?? metadata.security_id ?? null,
      symbol: security?.symbol ?? normalizeText(metadata.symbol).toUpperCase(),
      requestedRange: getMarketDataResponseRange(response),
      interval: getMarketDataResponseInterval(response),
      count: Number(metadata.count ?? visibleData.length),
      warmupCount: Number(metadata.warmup_count ?? warmupCandles.length),
      firstDatetime: normalizeText(metadata.first_datetime ?? visibleData[0]?.date),
      lastDatetime: normalizeText(metadata.last_datetime ?? visibleData.at(-1)?.date),
    },
    apiLastRecord: values.at(-1) ?? null,
    normalizedLastRecord: visibleData.at(-1) ?? null,
    fullData,
    visibleData,
    candles: visibleData,
    warmupCandles,
  }
}

export function getMarketDataDebugSummary({ request, response, marketData, chart }) {
  const apiValues = Array.isArray(response?.values) ? response.values : []
  const visibleData = marketData?.visibleData ?? marketData?.candles ?? []
  const fullData = marketData?.fullData ?? [
    ...(marketData?.warmupCandles ?? []),
    ...visibleData,
  ]
  const chartCandles = chart?.candles ?? visibleData
  const firstVisibleCandle = visibleData[0]
  const lastVisibleCandle = visibleData.at(-1)
  const finalChartLastRecord = chartCandles.at(-1) ?? null

  return {
    securityId: request?.securityId,
    symbol: marketData?.metadata?.symbol || response?.security?.symbol || '',
    range: request?.range,
    interval: request?.interval,
    apiCount: apiValues.length,
    warmupCount: marketData?.warmupCandles?.length ?? 0,
    firstDatetime: firstVisibleCandle?.date ?? '',
    firstClose: firstVisibleCandle?.close ?? null,
    lastDatetime: lastVisibleCandle?.date ?? '',
    lastClose: lastVisibleCandle?.close ?? null,
    chartCount: chartCandles.length,
    chartLastClose: finalChartLastRecord?.close ?? null,
    dailyApiLastRecord: apiValues.at(-1) ?? null,
    normalizedLastRecord: marketData?.normalizedLastRecord ?? lastVisibleCandle ?? null,
    fullDataLastRecord: fullData.at(-1) ?? null,
    visibleDataLastRecord: lastVisibleCandle ?? null,
    finalChartDataLastRecord: finalChartLastRecord,
    topPriceValue: chart?.debug?.topPriceValue ?? finalChartLastRecord?.close ?? null,
    topPriceSource: chart?.debug?.topPriceSource ?? 'visibleData[visibleData.length - 1].close',
    previousClose: chart?.debug?.previousCloseValue ?? null,
    previousCloseSource: chart?.debug?.previousCloseSource ?? '',
    dailyChange: chart?.debug?.dailyChangeValue ?? null,
    dailyChangePercent: chart?.debug?.dailyChangePercent ?? null,
    provider: response?.metadata?.provider ?? {},
    sessionCloseAdjustments: response?.metadata?.session_close_adjustments ?? [],
  }
}

export function formatIntervalLabel(interval) {
  const normalizedInterval = normalizeText(interval).toLowerCase()
  if (normalizedInterval === '1min') return '1-minute OHLCV'
  if (normalizedInterval === '5min') return '5-minute OHLCV'
  if (normalizedInterval === '15min') return '15-minute OHLCV'
  if (normalizedInterval === '30min') return '30-minute OHLCV'
  if (normalizedInterval === '1h') return 'hourly OHLCV'
  if (normalizedInterval === '2h') return '2-hour OHLCV'
  if (normalizedInterval === '4h') return '4-hour OHLCV'
  if (normalizedInterval === '1week') return 'weekly OHLCV'
  return 'daily OHLCV'
}

export function buildDashboardIndicators(candles, warmupCandles = []) {
  if (!candles.length) return []

  const calculationCandles = [...warmupCandles, ...candles]
  const closes = calculationCandles.map((candle) => candle.close)
  const macd = macdSeries(closes, 12, 26, 9)
  const rsiLine = rsiSeries(closes, 14)

  return calculationCandles.map((_, index) => ({
    macd: macd.macd[index],
    signal: macd.signal[index],
    histogram: macd.histogram[index],
    rsi: rsiLine[index],
  })).slice(-candles.length)
}

function buildDashboardIndicatorsFromFullData(fullData, visibleData) {
  if (!visibleData.length) return []
  if (!fullData.length) return buildDashboardIndicators(visibleData)

  const visibleStartDate = visibleData[0]?.date
  const visibleStartIndex = fullData.findIndex((candle) => candle.date === visibleStartDate)
  if (visibleStartIndex === -1) return buildDashboardIndicators(visibleData)

  const closes = fullData.map((candle) => candle.close)
  const macd = macdSeries(closes, 12, 26, 9)
  const rsiLine = rsiSeries(closes, 14)

  return fullData.map((_, index) => ({
    macd: macd.macd[index],
    signal: macd.signal[index],
    histogram: macd.histogram[index],
    rsi: rsiLine[index],
  })).slice(visibleStartIndex, visibleStartIndex + visibleData.length)
}

function hasStableMacd(indicators) {
  return indicators.some((indicator) => (
    Number.isFinite(indicator.macd)
    && Number.isFinite(indicator.signal)
    && Number.isFinite(indicator.histogram)
  ))
}

function hasStableRsi(indicators) {
  return indicators.some((indicator) => Number.isFinite(indicator.rsi))
}

function getCandleMarketDate(candle) {
  return normalizeText(candle?.marketDate || candle?.date).slice(0, 10)
}

function getPreviousSessionClose(fullData, latestCandle) {
  const latestMarketDate = getCandleMarketDate(latestCandle)
  if (!latestMarketDate) return null

  const previousSessionCandle = [...fullData]
    .reverse()
    .find((candle) => getCandleMarketDate(candle) && getCandleMarketDate(candle) < latestMarketDate)
  return previousSessionCandle ?? null
}

function formatIndicatorNumber(value, digits = 2) {
  return Number.isFinite(value) ? value.toFixed(digits) : 'N/A'
}

function formatIndicatorPercent(value) {
  return Number.isFinite(value) ? `${value.toFixed(2)}%` : 'N/A'
}

function getRsiSignal(rsi) {
  if (!Number.isFinite(rsi)) return { signal: 'Insufficient', tone: 'neutral', level: 0 }
  if (rsi >= 70) return { signal: 'Overbought', tone: 'warning', level: clampNumber(rsi, 0, 100) }
  if (rsi <= 30) return { signal: 'Oversold', tone: 'warning', level: clampNumber(rsi, 0, 100) }
  return { signal: 'Neutral', tone: 'neutral', level: clampNumber(rsi, 0, 100) }
}

function getMacdSignal(macd, signal) {
  if (!Number.isFinite(macd) || !Number.isFinite(signal)) {
    return { signal: 'Insufficient', tone: 'neutral', level: 0 }
  }
  if (macd > signal) return { signal: 'Bullish', tone: 'positive', level: 72 }
  if (macd < signal) return { signal: 'Bearish', tone: 'warning', level: 38 }
  return { signal: 'Neutral', tone: 'neutral', level: 50 }
}

function getMovingAverageSignal(latestClose, movingAverage) {
  if (!Number.isFinite(latestClose) || !Number.isFinite(movingAverage)) {
    return { signal: 'Insufficient', tone: 'neutral', level: 0 }
  }
  if (latestClose > movingAverage) return { signal: 'Above', tone: 'positive', level: 72 }
  if (latestClose < movingAverage) return { signal: 'Below', tone: 'warning', level: 38 }
  return { signal: 'At MA', tone: 'neutral', level: 50 }
}

function getVolatilitySignal(volatility) {
  if (!Number.isFinite(volatility)) return { signal: 'Insufficient', tone: 'neutral', level: 0 }
  if (volatility < 1.5) return { signal: 'Low', tone: 'neutral', level: 32 }
  if (volatility <= 4) return { signal: 'Moderate', tone: 'neutral', level: 56 }
  return { signal: 'High', tone: 'warning', level: 84 }
}

function averageFinite(values) {
  const finiteValues = values.filter(Number.isFinite)
  if (!finiteValues.length) return null
  return finiteValues.reduce((sum, value) => sum + value, 0) / finiteValues.length
}

function getCompositeSignal({ latestClose, macdHistogram, macdLine, macdSignal, movingAverage, rsi, volatility }) {
  const score = averageFinite([
    Number.isFinite(rsi) ? (rsi >= 70 ? 40 : rsi <= 30 ? 60 : rsi) : null,
    Number.isFinite(macdHistogram)
      ? macdHistogram > 0 ? 65 : macdHistogram < 0 ? 35 : 50
      : Number.isFinite(macdLine) && Number.isFinite(macdSignal)
        ? macdLine > macdSignal ? 65 : macdLine < macdSignal ? 35 : 50
        : null,
    Number.isFinite(latestClose) && Number.isFinite(movingAverage)
      ? latestClose > movingAverage ? 65 : latestClose < movingAverage ? 35 : 50
      : null,
    Number.isFinite(volatility)
      ? volatility < 1.5 ? 60 : volatility <= 4 ? 50 : 40
      : null,
  ])

  if (!Number.isFinite(score)) return { signal: 'N/A', score: null }
  if (score >= 60) return { signal: 'Bullish', score: Math.round(score) }
  if (score <= 40) return { signal: 'Bearish', score: Math.round(score) }
  return { signal: 'Neutral', score: Math.round(score) }
}

export function buildDashboardTechnicalIndicators(chart) {
  const visibleData = chart?.visibleData ?? chart?.candles ?? []
  const fullData = chart?.fullData?.length ? chart.fullData : visibleData
  const latestCandle = visibleData.at(-1)
  const latestClose = latestCandle?.close
  const closes = fullData.map((candle) => candle.close)
  const indicators = chart?.indicators ?? []
  const latestRsi = findLastFinite(indicators.map((indicator) => indicator.rsi))
  const latestMacdIndex = indicators.findLastIndex((indicator) => (
    Number.isFinite(indicator.macd)
    && Number.isFinite(indicator.signal)
    && Number.isFinite(indicator.histogram)
  ))
  const latestMacd = latestMacdIndex >= 0 ? indicators[latestMacdIndex] : {}
  const ma20 = findLastFinite(movingAverageSeries(closes, 20))
  const volatility = realizedVolatility(closes, 20)
  const rsiSignal = getRsiSignal(latestRsi)
  const macdSignal = getMacdSignal(latestMacd.macd, latestMacd.signal)
  const movingAverageSignal = getMovingAverageSignal(latestClose, ma20)
  const volatilitySignal = getVolatilitySignal(volatility)
  const compositeSignal = getCompositeSignal({
    latestClose,
    macdHistogram: latestMacd.histogram,
    macdLine: latestMacd.macd,
    macdSignal: latestMacd.signal,
    movingAverage: ma20,
    rsi: latestRsi,
    volatility,
  })

  return {
    signal: compositeSignal.signal,
    score: compositeSignal.score,
    sourceLabel: chart?.isLoading
      ? 'Loading real OHLCV indicators'
      : chart?.error
        ? 'Real OHLCV indicators unavailable'
        : 'Real OHLCV signal snapshot',
    notice: chart?.error || chart?.indicatorWarnings?.rsi || chart?.indicatorWarnings?.macd || '',
    items: [
      {
        name: 'RSI (14)',
        value: formatIndicatorNumber(latestRsi, 1),
        ...rsiSignal,
      },
      {
        name: 'MACD',
        value: formatIndicatorNumber(latestMacd.histogram, 2),
        ...macdSignal,
      },
      {
        name: 'Moving Avg. (20)',
        value: Number.isFinite(ma20) ? formatCurrency(ma20, chart?.currency ?? 'USD') : 'N/A',
        ...movingAverageSignal,
      },
      {
        name: 'Volatility',
        value: formatIndicatorPercent(volatility),
        ...volatilitySignal,
      },
    ],
  }
}

export function buildDashboardPriceChart({ security, marketData, range, requestedInterval, isLoading = false, error = '' }) {
  const visibleData = marketData?.visibleData ?? marketData?.candles ?? []
  const fullData = marketData?.fullData ?? [
    ...(marketData?.warmupCandles ?? []),
    ...visibleData,
  ]
  const candles = visibleData
  const interval = marketData?.interval ?? requestedInterval ?? '1day'
  const intervalLabel = formatIntervalLabel(interval)
  const indicators = buildDashboardIndicatorsFromFullData(fullData, visibleData)
  const firstCandle = candles.at(0)
  const latestCandle = candles.at(-1)
  const previousSessionCandle = latestCandle ? getPreviousSessionClose(fullData, latestCandle) : null
  const changeValue = latestCandle && previousSessionCandle ? latestCandle.close - previousSessionCandle.close : null
  const changePercent = latestCandle && previousSessionCandle && previousSessionCandle.close
    ? (changeValue / previousSessionCandle.close) * 100
    : null
  const quoteTone = changeValue > 0 ? 'up' : changeValue < 0 ? 'down' : 'neutral'
  const dataSourceNote = marketData?.isStale
    ? 'Security details from Django API. OHLCV is cached Twelve Data daily data and may be stale.'
    : `Security details from Django API. Candles and volume use Twelve Data ${intervalLabel} through the Django market-data API. Latest available price uses the last returned OHLCV close.`

  return {
    symbol: security.symbol,
    company: security.name,
    currency: security.currency,
    dataKey: [
      marketData?.metadata?.securityId ?? security.id,
      marketData?.metadata?.requestedRange ?? range,
      interval,
      candles.length,
      firstCandle?.date ?? '',
      firstCandle?.close ?? '',
      latestCandle?.date ?? '',
      latestCandle?.close ?? '',
    ].join('|'),
    price: latestCandle ? formatCurrency(latestCandle.close, security.currency) : 'OHLCV unavailable',
    change: changeValue === null ? 'N/A' : formatSignedCurrency(changeValue, security.currency),
    percent: changePercent === null ? 'N/A' : formatSignedPercent(changePercent),
    range,
    ranges: dashboardMarketDataRanges,
    intervalOptions: dashboardMarketDataIntervals,
    fullData,
    visibleData,
    candles,
    indicators,
    indicatorWarnings: {
      macd: candles.length && !hasStableMacd(indicators) ? 'Insufficient historical data for MACD.' : '',
      rsi: candles.length && !hasStableRsi(indicators) ? 'Insufficient historical data for RSI.' : '',
    },
    interval,
    intervalLabel,
    labels: candles.map((candle) => formatDashboardDateLabel(candle.date, interval, range)),
    quoteTone,
    dataSourceNote,
    isLoading,
    error,
    isEmpty: !isLoading && !error && candles.length === 0,
    debug: {
      fullDataLastRecord: fullData.at(-1) ?? null,
      visibleDataLastRecord: latestCandle ?? null,
      finalChartDataLastRecord: candles.at(-1) ?? null,
      topPriceValue: latestCandle?.close ?? null,
      topPriceSource: 'visibleData[visibleData.length - 1].close',
      previousCloseValue: previousSessionCandle?.close ?? null,
      previousCloseSource: 'last fullData candle before latest marketDate',
      dailyChangeValue: changeValue,
      dailyChangePercent: changePercent,
    },
  }
}
