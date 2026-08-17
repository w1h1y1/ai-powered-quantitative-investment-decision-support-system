const regimeLabels = {
  bullish_trend: 'Bullish Trend',
  bearish_trend: 'Bearish Trend',
  sideways_range: 'Sideways / Range',
  high_volatility: 'High Volatility',
}

const regimeTones = {
  bullish_trend: 'positive',
  bearish_trend: 'negative',
  sideways_range: 'neutral',
  high_volatility: 'warning',
}

const trendDirectionLabels = {
  bearish: 'Bearish',
  bullish: 'Bullish',
  mixed: 'Mixed',
  neutral: 'Neutral',
}

const trendDirectionTones = {
  bearish: 'negative',
  bullish: 'positive',
  mixed: 'neutral',
  neutral: 'neutral',
}

function finiteNumber(value) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function normalizedSymbol(value) {
  return String(value ?? '').trim().toUpperCase()
}

function explanationContains(explanations, text) {
  return explanations.some((item) => item.toLowerCase().includes(text))
}

function trendStrength(explanations) {
  if (explanationContains(explanations, 'strong trend')) return 'Strong'
  if (explanationContains(explanations, 'meaningful trend')) return 'Meaningful'
  if (explanationContains(explanations, 'forming trend')) return 'Forming'
  if (explanationContains(explanations, 'weak or absent trend')) return 'Weak / Absent'
  return 'N/A'
}

function rangeCondition(explanations) {
  if (explanationContains(explanations, 'range-friendly')) return 'Range-Friendly'
  if (explanationContains(explanations, 'trend-friendly')) return 'Trend-Friendly'
  if (explanationContains(explanations, 'mixed zone')) return 'Mixed'
  return 'N/A'
}

function momentumSignal(explanations, score) {
  if (explanationContains(explanations, 'positive momentum')) return 'Positive'
  if (explanationContains(explanations, 'negative momentum')) return 'Negative'
  if (explanationContains(explanations, 'mixed or weak')) return 'Neutral'
  if (score > 0) return 'Positive'
  if (score < 0) return 'Negative'
  if (score === 0) return 'Neutral'
  return 'N/A'
}

function displaySource(source) {
  const normalized = String(source ?? '').trim().toLowerCase()
  if (normalized === 'database_cache') return 'Cached market data'
  if (normalized === 'twelve_data') return 'Twelve Data'
  return source || 'N/A'
}

export function formatRegimeLabel(regime) {
  return regimeLabels[regime] ?? 'N/A'
}

export function formatNumber(value, digits = 2) {
  const number = finiteNumber(value)
  return number === null ? 'N/A' : number.toFixed(digits)
}

export function formatPercent(value, { digits = 2, signed = false } = {}) {
  const number = finiteNumber(value)
  if (number === null) return 'N/A'
  const percent = number * 100
  const prefix = signed && percent > 0 ? '+' : ''
  return `${prefix}${percent.toFixed(digits)}%`
}

export function formatPercentile(value) {
  const number = finiteNumber(value)
  if (number === null) return 'N/A'
  const percentile = Math.round(number * 100)
  const modulo100 = percentile % 100
  const suffix = modulo100 >= 11 && modulo100 <= 13
    ? 'th'
    : percentile % 10 === 1
      ? 'st'
      : percentile % 10 === 2
        ? 'nd'
        : percentile % 10 === 3
          ? 'rd'
          : 'th'
  return `${percentile}${suffix} percentile`
}

export function formatMarketDate(value) {
  const match = String(value ?? '').match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (!match) return value || 'N/A'
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])))
  return new Intl.DateTimeFormat('en-US', {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
    year: 'numeric',
  }).format(date)
}

export function formatUnavailableReason(reason) {
  const messages = {
    insufficient_history: 'Insufficient historical data to calculate the market regime.',
    security_not_available: 'The selected security is not available for market-regime analysis.',
  }
  if (messages[reason]) return messages[reason]
  if (!reason) return 'Market regime is unavailable for the selected security.'
  return String(reason)
    .replaceAll('_', ' ')
    .replace(/^./, (letter) => letter.toUpperCase())
    .replace(/\.?$/, '.')
}

export function marketRegimeResponseMatchesSymbol(response, expectedSymbol) {
  return normalizedSymbol(response?.symbol) === normalizedSymbol(expectedSymbol)
}

export function marketRegimeResponseMatchesSecurity(response, expectedSymbol, expectedSecurityId) {
  if (!marketRegimeResponseMatchesSymbol(response, expectedSymbol)) return false
  if (expectedSecurityId === null || expectedSecurityId === undefined || expectedSecurityId === '') return true
  return String(response?.security_id ?? '') === String(expectedSecurityId)
}

export function isCurrentMarketRegimeRequest(currentRequestId, responseRequestId) {
  return currentRequestId === responseRequestId
}

export function getMarketRegimePanelState(requestState, selectedSymbol) {
  const symbol = normalizedSymbol(selectedSymbol)
  if (!symbol) return { status: 'idle', symbol, data: null, error: '' }
  if (normalizedSymbol(requestState?.symbol) !== symbol) {
    return { status: 'loading', symbol, data: null, error: '' }
  }
  return {
    status: requestState?.status || 'loading',
    symbol,
    data: requestState?.data ?? null,
    error: requestState?.error ?? '',
  }
}

export function normalizeMarketRegime(response, expectedSymbol, expectedSecurityId) {
  if (!marketRegimeResponseMatchesSecurity(response, expectedSymbol, expectedSecurityId)) {
    throw new Error('Market regime response did not match the selected stock.')
  }

  const explanations = Array.isArray(response?.explanation)
    ? response.explanation.filter((item) => typeof item === 'string' && item.trim())
    : []
  const trend = response?.trend ?? {}
  const momentum = response?.momentum ?? {}
  const volatility = response?.volatility ?? {}
  const range = response?.range ?? {}
  const relativeStrength = response?.relative_strength ?? {}
  const context = response?.market_context ?? {}
  const stockMarketData = response?.market_data?.stock ?? {}
  const trendScore = finiteNumber(trend.score)
  const momentumScore = finiteNumber(momentum.score)
  const rawTrendDirection = String(trend.direction ?? '').trim().toLowerCase()
  const direction = trendDirectionLabels[rawTrendDirection] ?? 'N/A'
  const directionTone = trendDirectionTones[rawTrendDirection] ?? 'neutral'
  const signal = momentumSignal(explanations, momentumScore)

  return {
    symbol: normalizedSymbol(response.symbol),
    securityId: response.security_id ?? null,
    available: response.regime_available === true,
    unavailableReason: formatUnavailableReason(response.regime_unavailable_reason),
    regime: response.regime ?? null,
    regimeLabel: formatRegimeLabel(response.regime),
    regimeTone: regimeTones[response.regime] ?? 'neutral',
    confidence: response.confidence
      ? String(response.confidence).replace(/^./, (letter) => letter.toUpperCase())
      : 'N/A',
    confidenceScore: finiteNumber(response.confidence_score),
    trend: {
      direction,
      tone: directionTone,
      strength: trendStrength(explanations),
      adx: finiteNumber(trend.adx),
      score: trendScore,
    },
    momentum: {
      signal,
      tone: signal === 'Positive' ? 'positive' : signal === 'Negative' ? 'negative' : 'neutral',
      rsi: finiteNumber(momentum.rsi),
      macdHistogram: finiteNumber(momentum.macd_histogram),
      return20d: finiteNumber(momentum.return_20d),
      return60d: finiteNumber(momentum.return_60d),
    },
    volatility: {
      atrPercent: finiteNumber(volatility.atr_percent),
      realized20d: finiteNumber(volatility.realized_volatility_20d),
      percentile: finiteNumber(volatility.volatility_percentile),
      percentileAvailable: volatility.percentile_available === true,
      percentileUnavailableReason: volatility.percentile_unavailable_reason ?? null,
    },
    range: {
      condition: rangeCondition(explanations),
      choppiness: finiteNumber(range.choppiness),
      score: finiteNumber(range.score),
    },
    marketContext: {
      broadMarket: context.broad_market || 'SPY',
      broadMarketAvailable: context.broad_market_context_available === true,
      broadMarketReason: context.broad_market_context_reason ?? null,
      spyRegime: context.spy_regime ?? null,
      sector: context.sector || response.sector || 'N/A',
      sectorBenchmark: context.sector_benchmark || response.sector_benchmark || 'N/A',
      sectorAvailable: context.sector_context_available === true,
      sectorReason: context.sector_context_reason ?? response.sector_context_reason ?? null,
      sectorRegime: context.sector_regime ?? null,
      confirmationScore: finiteNumber(context.confirmation_score),
    },
    relativeStrength: {
      score: finiteNumber(relativeStrength.score),
      vsSpy20d: finiteNumber(relativeStrength.vs_spy_20d),
      vsSpy60d: finiteNumber(relativeStrength.vs_spy_60d),
      vsSector20d: finiteNumber(relativeStrength.vs_sector_20d),
      vsSector60d: finiteNumber(relativeStrength.vs_sector_60d),
    },
    explanations,
    freshness: {
      latestMarketDate: response.latest_market_date || stockMarketData.last_date || null,
      source: displaySource(stockMarketData.source),
      fetchedFromProvider: stockMarketData.fetched_from_provider === true,
    },
  }
}
