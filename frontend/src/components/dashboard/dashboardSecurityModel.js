export const dashboardSecurityStorageKey = 'aiquantification.dashboard.selectedSecurityId'

export const dashboardMarketDataRanges = ['1M', '3M', '6M', 'YTD', '1Y', '3Y', '5Y', 'Custom']

function getDefaultStorage() {
  return typeof window === 'undefined' ? null : window.localStorage
}

function normalizeText(value) {
  return String(value ?? '').trim()
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
    isActive: security.is_active === true,
  }
}

export function getActiveSecurities(response) {
  if (!Array.isArray(response)) return []

  return response
    .map(normalizeSecurity)
    .filter((security) => security?.id && security.symbol && security.name && security.isActive)
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

function formatDateLabel(value) {
  const parsedDate = new Date(`${value}T00:00:00Z`)
  if (Number.isNaN(parsedDate.getTime())) return value
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
  }).format(parsedDate)
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

export function isCustomMarketDataRange(range) {
  return normalizeText(range).toUpperCase() === 'CUSTOM'
}

export function getTodayDateInputValue(now = new Date()) {
  return formatDateInputValue(now)
}

export function createDefaultCustomMarketDataRange(now = new Date()) {
  const endDate = formatDateInputValue(now)
  const startDate = formatDateInputValue(subtractLocalMonths(now, 1))
  return { startDate, endDate }
}

export function validateCustomMarketDataRange(range, today = getTodayDateInputValue()) {
  const startDate = normalizeText(range?.startDate)
  const endDate = normalizeText(range?.endDate)

  if (!isValidDateInput(startDate) || !isValidDateInput(endDate)) {
    return 'Select valid start and end dates.'
  }
  if (startDate > endDate) {
    return 'Start date cannot be later than end date.'
  }
  if (startDate > today || endDate > today) {
    return 'Custom range cannot include future dates.'
  }
  return ''
}

export function buildMarketDataRequestParams({ security, range, customRange }) {
  const request = {
    securityId: security.id,
    range,
  }

  if (isCustomMarketDataRange(range)) {
    request.startDate = customRange?.startDate
    request.endDate = customRange?.endDate
  }

  return request
}

export function shouldApplyMarketDataResponse(activeRequestId, responseRequestId) {
  return activeRequestId === responseRequestId
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

export function normalizeMarketData(response) {
  const values = Array.isArray(response?.values) ? response.values : []

  return {
    range: response?.range,
    source: response?.source,
    isStale: response?.is_stale === true,
    candles: values.map((item) => ({
      date: item.date,
      open: parseNumber(item.open),
      high: parseNumber(item.high),
      low: parseNumber(item.low),
      close: parseNumber(item.close),
      volume: parseNumber(item.volume),
    })).filter((item) => item.date && item.high >= item.low),
  }
}

export function buildDashboardPriceChart({ security, marketData, range, isLoading = false, error = '' }) {
  const candles = marketData?.candles ?? []
  const latestCandle = candles.at(-1)
  const previousCandle = candles.at(-2)
  const changeValue = latestCandle && previousCandle ? latestCandle.close - previousCandle.close : null
  const changePercent = latestCandle && previousCandle && previousCandle.close
    ? (changeValue / previousCandle.close) * 100
    : null
  const quoteTone = changeValue > 0 ? 'up' : changeValue < 0 ? 'down' : 'neutral'
  const dataSourceNote = marketData?.isStale
    ? 'Security details from Django API. OHLCV is cached Twelve Data daily data and may be stale.'
    : 'Security details from Django API. Candles and volume use cached Twelve Data daily OHLCV.'

  return {
    symbol: security.symbol,
    company: security.name,
    currency: security.currency,
    price: latestCandle ? formatCurrency(latestCandle.close, security.currency) : 'OHLCV unavailable',
    change: changeValue === null ? 'N/A' : formatSignedCurrency(changeValue, security.currency),
    percent: changePercent === null ? 'N/A' : formatSignedPercent(changePercent),
    range,
    ranges: dashboardMarketDataRanges,
    candles,
    labels: candles.map((candle) => formatDateLabel(candle.date)),
    quoteTone,
    dataSourceNote,
    isLoading,
    error,
    isEmpty: !isLoading && !error && candles.length === 0,
  }
}
