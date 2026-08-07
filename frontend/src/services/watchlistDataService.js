import {
  findLastFinite,
  macdSeries,
  movingAverageSeries,
  rsiSeries,
} from '../utils/technicalIndicators.js'
import { securityApi } from './securityApi.js'
import { watchlistApi } from './watchlistApi.js'

const PLACEHOLDER = '\u2014'
export const watchlistDataChangedEventName = 'aiquantification:watchlist-changed'

let watchlistDataRequestPromise = null

function parseNumber(value) {
  if (value === null || value === undefined || String(value).trim() === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function formatWatchlistCurrency(value, currency = 'USD') {
  if (!Number.isFinite(value)) return PLACEHOLDER

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

export function formatWatchlistSignedCurrency(value, currency = 'USD') {
  if (!Number.isFinite(value)) return PLACEHOLDER

  const sign = value >= 0 ? '+' : '-'
  return `${sign}${formatWatchlistCurrency(Math.abs(value), currency)}`
}

export function formatWatchlistSignedPercent(value) {
  if (!Number.isFinite(value)) return PLACEHOLDER

  const sign = value >= 0 ? '+' : '-'
  return `${sign}${Math.abs(value).toFixed(2)}%`
}

export function getWatchlistStatusTone(status) {
  if (status === 'Bullish' || status === 'Uptrend') return 'is-positive'
  if (status === 'Bearish' || status === 'Downtrend') return 'is-negative'
  if (status === 'Overbought' || status === 'Oversold' || status === 'Near Overbought' || status === 'Near Oversold') return 'is-warning'
  return 'is-neutral'
}

export function normalizeWatchlistSecurity(security) {
  if (!security) return null

  return {
    id: security.id,
    symbol: String(security.symbol ?? '').trim().toUpperCase(),
    company: String(security.name ?? '').trim(),
    assetType: security.asset_type,
    exchange: security.exchange,
    currency: String(security.currency ?? 'USD').trim().toUpperCase(),
    isActive: security.is_active !== false,
  }
}

export function normalizeWatchlistQuote(response) {
  const securityId = response?.security?.id
  if (!securityId) return null

  const dataStatus = String(response.data_status || 'ok').toLowerCase()
  const price = dataStatus === 'unavailable' ? null : parseNumber(response.price)
  const change = dataStatus === 'unavailable' ? null : parseNumber(response.change)
  const changePercent = dataStatus === 'unavailable' ? null : parseNumber(response.percent_change)

  return {
    securityId,
    price,
    change,
    changePercent,
    currency: response.currency || response.security?.currency || 'USD',
    source: response.source || '',
    asOf: response.as_of || '',
    dataStatus,
    cacheStatus: response.cache_status || '',
    isStale: response.is_stale === true,
    error: response.error || '',
  }
}

export function normalizeWatchlistQuotes(response) {
  const quotesBySecurityId = new Map()
  const items = Array.isArray(response?.items) ? response.items : []

  items.forEach((item) => {
    const quote = normalizeWatchlistQuote(item)
    if (quote) quotesBySecurityId.set(quote.securityId, quote)
  })

  return quotesBySecurityId
}

function normalizeWatchlistSummaryQuote(response, security) {
  if (!response) return null

  const dataStatus = String(response.data_status || 'ok').toLowerCase()
  const price = dataStatus === 'unavailable' ? null : parseNumber(response.price)
  const change = dataStatus === 'unavailable' ? null : parseNumber(response.change)
  const changePercent = dataStatus === 'unavailable' ? null : parseNumber(response.percent_change)

  return {
    securityId: security?.id,
    price,
    change,
    changePercent,
    currency: response.currency || security?.currency || 'USD',
    source: response.source || '',
    asOf: response.as_of || '',
    dataStatus,
    cacheStatus: response.cache_status || '',
    isStale: response.is_stale === true,
    error: response.error || '',
  }
}

function normalizeClosePoints(points) {
  return (Array.isArray(points) ? points : [])
    .map((point) => ({
      date: String(point?.date ?? ''),
      close: parseNumber(point?.close),
    }))
    .filter((point) => point.date && Number.isFinite(point.close))
    .sort((a, b) => a.date.localeCompare(b.date))
}

function normalizeWatchlistSummaryHistory(response) {
  const miniTrendPoints = normalizeClosePoints(response?.mini_trend)
  const indicatorClosePoints = normalizeClosePoints(response?.indicator_closes)

  return {
    range: response?.range || '',
    interval: response?.interval || '',
    source: response?.source || '',
    dataSource: response?.data_source || '',
    cacheStatus: response?.cache_status || '',
    dataStatus: String(response?.data_status || 'unavailable').toLowerCase(),
    isStale: response?.is_stale === true,
    error: response?.error || '',
    latestAsOf: response?.latest_as_of || '',
    miniTrend: miniTrendPoints.map((point) => point.close),
    indicatorCloses: indicatorClosePoints.map((point) => point.close),
  }
}

function getRsiStatus(rsi) {
  if (!Number.isFinite(rsi)) return 'N/A'
  if (rsi >= 70) return 'Overbought'
  if (rsi <= 30) return 'Oversold'
  return 'Neutral'
}

function getMacdStatus(macd, signal, histogram) {
  if (!Number.isFinite(macd) || !Number.isFinite(signal) || !Number.isFinite(histogram)) return 'N/A'
  if (macd > signal && histogram > 0) return 'Bullish'
  if (macd < signal && histogram < 0) return 'Bearish'
  return 'Neutral'
}

function getOverallTrend({ latestPrice, ma5, ma20, macdStatus }) {
  const hasPriceAndMa20 = Number.isFinite(latestPrice) && Number.isFinite(ma20)
  const hasMaCross = Number.isFinite(ma5) && Number.isFinite(ma20)
  const hasMacdStatus = macdStatus && macdStatus !== 'N/A'
  const bullishSignals = [
    hasPriceAndMa20 ? latestPrice > ma20 : null,
    hasMaCross ? ma5 > ma20 : null,
    hasMacdStatus ? macdStatus === 'Bullish' : null,
  ].filter((value) => value !== null)
  const bearishSignals = [
    hasPriceAndMa20 ? latestPrice < ma20 : null,
    hasMaCross ? ma5 < ma20 : null,
    hasMacdStatus ? macdStatus === 'Bearish' : null,
  ].filter((value) => value !== null)

  if (!bullishSignals.length && !bearishSignals.length) return 'N/A'
  if (bullishSignals.filter(Boolean).length >= 2) return 'Uptrend'
  if (bearishSignals.filter(Boolean).length >= 2) return 'Downtrend'
  return 'Sideways'
}

export function buildWatchlistTechnicalStatus(closes, latestPrice = null) {
  const cleanCloses = (Array.isArray(closes) ? closes : []).filter(Number.isFinite)
  const latestClose = Number.isFinite(latestPrice) ? latestPrice : cleanCloses.at(-1)
  const rsi = findLastFinite(rsiSeries(cleanCloses, 14))
  const macd = macdSeries(cleanCloses, 12, 26, 9)
  const latestMacdIndex = macd.macd.findLastIndex((value, index) => (
    Number.isFinite(value)
    && Number.isFinite(macd.signal[index])
    && Number.isFinite(macd.histogram[index])
  ))
  const latestMacd = latestMacdIndex >= 0 ? macd.macd[latestMacdIndex] : null
  const latestSignal = latestMacdIndex >= 0 ? macd.signal[latestMacdIndex] : null
  const latestHistogram = latestMacdIndex >= 0 ? macd.histogram[latestMacdIndex] : null
  const ma5 = findLastFinite(movingAverageSeries(cleanCloses, 5))
  const ma20 = findLastFinite(movingAverageSeries(cleanCloses, 20))
  const rsiStatus = getRsiStatus(rsi)
  const macdStatus = getMacdStatus(latestMacd, latestSignal, latestHistogram)

  return {
    rsi,
    macd: latestMacd,
    macdSignal: latestSignal,
    macdHistogram: latestHistogram,
    ma5,
    ma20,
    rsiStatus,
    macdStatus,
    overallTrend: getOverallTrend({
      latestPrice: latestClose,
      ma5,
      ma20,
      macdStatus,
    }),
  }
}

function getWatchlistItemSecurity(item, securitiesById) {
  const nestedSecurity = item?.security
  if (!nestedSecurity) return null
  return securitiesById.get(nestedSecurity.id) ?? nestedSecurity
}

export function buildWatchlistStock(security, itemId = null, summaryItem = null) {
  const normalizedSecurity = normalizeWatchlistSecurity(security)
  if (!normalizedSecurity) return null
  const quote = normalizeWatchlistSummaryQuote(summaryItem?.quote, normalizedSecurity)
  const history = normalizeWatchlistSummaryHistory(summaryItem?.history)
  const miniTrend = history.miniTrend.length >= 2 ? history.miniTrend : []
  const hasQuote = quote?.securityId === normalizedSecurity.id && Number.isFinite(quote.price)
  const quoteChange = hasQuote ? quote.change : null
  const direction = quoteChange > 0 ? 'up' : quoteChange < 0 ? 'down' : 'neutral'
  const currency = hasQuote ? quote.currency : normalizedSecurity.currency
  const technicalStatus = buildWatchlistTechnicalStatus(history.indicatorCloses, hasQuote ? quote.price : null)

  return {
    ...normalizedSecurity,
    itemId,
    name: normalizedSecurity.company,
    price: hasQuote ? quote.price : null,
    priceLabel: formatWatchlistCurrency(hasQuote ? quote.price : null, currency),
    dailyChange: quoteChange,
    changeLabel: formatWatchlistSignedCurrency(quoteChange, currency),
    changePercent: hasQuote ? quote.changePercent : null,
    changePercentLabel: formatWatchlistSignedPercent(hasQuote ? quote.changePercent : null),
    currency,
    direction,
    trend: miniTrend,
    quoteSource: quote?.source ?? '',
    quoteDataStatus: quote?.dataStatus ?? 'unavailable',
    quoteCacheStatus: quote?.cacheStatus ?? '',
    quoteIsStale: quote?.isStale === true,
    quoteError: quote?.error ?? '',
    latestAsOf: quote?.asOf || history.latestAsOf,
    historySource: history.source,
    historyDataStatus: history.dataStatus,
    historyCacheStatus: history.cacheStatus,
    historyError: history.error,
    rsiStatus: technicalStatus.rsiStatus,
    macdStatus: technicalStatus.macdStatus,
    overallTrend: technicalStatus.overallTrend,
    technicalStatus,
  }
}

export function getWatchlistErrorMessage(error) {
  const data = error?.data
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    if (data.security_id) {
      const message = Array.isArray(data.security_id) ? data.security_id[0] : data.security_id
      return String(message)
    }
    if (data.watchlist) {
      const message = Array.isArray(data.watchlist) ? data.watchlist[0] : data.watchlist
      return String(message)
    }
  }

  return error?.message || 'Request failed. Please try again.'
}

export function notifyWatchlistChanged() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new Event(watchlistDataChangedEventName))
}

async function fetchWatchlistData({ force = false } = {}) {
  const [summaryResponse, securitiesResponse] = await Promise.all([
    watchlistApi.summary({ refresh: force }),
    securityApi.list(),
  ])
  const securities = Array.isArray(securitiesResponse) ? securitiesResponse : []
  const currentWatchlist = summaryResponse?.watchlist ?? null
  const safeWatchlistItems = Array.isArray(summaryResponse?.watchlist_items) ? summaryResponse.watchlist_items : []
  const summaryItems = Array.isArray(summaryResponse?.items) ? summaryResponse.items : []
  const securitiesById = new Map(securities.map((security) => [security.id, security]))
  const summaryByItemId = new Map(summaryItems.map((item) => [item.item_id, item]))
  const metadataErrors = Array.isArray(summaryResponse?.metadata?.errors) ? summaryResponse.metadata.errors : []
  const quoteError = metadataErrors.length ? metadataErrors[0] : ''

  const selectedStocks = safeWatchlistItems
    .map((item) => {
      const security = getWatchlistItemSecurity(item, securitiesById)
      return buildWatchlistStock(security, item.id, summaryByItemId.get(item.id))
    })
    .filter(Boolean)

  return {
    watchlist: currentWatchlist,
    watchlistItems: safeWatchlistItems,
    securities,
    securityOptions: securities.map(normalizeWatchlistSecurity).filter((security) => security?.isActive),
    selectedStocks,
    summary: summaryResponse,
    quoteError,
  }
}

export function loadUserWatchlistData({ force = false } = {}) {
  if (!force && watchlistDataRequestPromise) return watchlistDataRequestPromise

  watchlistDataRequestPromise = fetchWatchlistData({ force }).finally(() => {
    watchlistDataRequestPromise = null
  })
  return watchlistDataRequestPromise
}

export function buildDashboardWatchlistItems(stocks, limit = 5) {
  return stocks.slice(0, limit).map((stock) => ({
    symbol: stock.symbol,
    name: stock.company,
    price: stock.priceLabel,
    change: stock.changePercentLabel,
    direction: stock.direction,
    trend: stock.trend,
    quoteError: stock.quoteError,
  }))
}
