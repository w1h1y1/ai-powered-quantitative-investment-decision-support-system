export const backtestHistoryStorageKey = 'aiquantification.backtest.history'
export const selectedBacktestStorageKey = 'aiquantification.backtest.selectedBacktestId'
export const legacySelectedBacktestStorageKey = 'selectedBacktestId'
export const backtestHistoryLimit = 8

export const backtestStrategies = [
  {
    id: 'ma-crossover',
    label: 'Moving Average Crossover',
    description: 'Compares a faster moving average with a slower trend average.',
    parameters: [
      { key: 'shortMa', label: 'Short MA period', min: 2, step: 1 },
      { key: 'longMa', label: 'Long MA period', min: 3, step: 1 },
    ],
  },
  {
    id: 'rsi',
    label: 'RSI Strategy',
    description: 'Uses momentum thresholds to identify potential entry and exit conditions.',
    parameters: [
      { key: 'rsiPeriod', label: 'RSI period', min: 2, step: 1 },
      { key: 'oversold', label: 'Oversold threshold', min: 0, max: 100, step: 1 },
      { key: 'overbought', label: 'Overbought threshold', min: 0, max: 100, step: 1 },
    ],
  },
  {
    id: 'macd',
    label: 'MACD Strategy',
    description: 'Uses fast, slow and signal exponential averages to evaluate momentum shifts.',
    parameters: [
      { key: 'fastPeriod', label: 'Fast period', min: 2, step: 1 },
      { key: 'slowPeriod', label: 'Slow period', min: 3, step: 1 },
      { key: 'signalPeriod', label: 'Signal period', min: 2, step: 1 },
    ],
  },
]

export const defaultBacktestConfig = {
  symbol: 'AAPL',
  strategyId: 'ma-crossover',
  startDate: '2025-07-01',
  endDate: '2026-06-30',
  initialCapital: '10000',
  tradingFee: '0.10',
  shortMa: '20',
  longMa: '50',
  rsiPeriod: '14',
  oversold: '30',
  overbought: '70',
  fastPeriod: '12',
  slowPeriod: '26',
  signalPeriod: '9',
}

const strategyProfiles = {
  'ma-crossover': { alpha: 0.0007, beta: 0.86, noise: 0.006 },
  rsi: { alpha: 0.00045, beta: 0.72, noise: 0.0065 },
  macd: { alpha: 0.0008, beta: 0.9, noise: 0.007 },
}

function parseNumericValue(value) {
  if (value === null || value === undefined || String(value).trim() === '') return Number.NaN
  return Number(value)
}

function isIntegerAtLeast(value, minimum) {
  const parsed = parseNumericValue(value)
  return Number.isInteger(parsed) && parsed >= minimum
}

export function validateBacktestConfig(config) {
  const errors = {}
  const strategy = backtestStrategies.find((item) => item.id === config.strategyId)
  const startTime = Date.parse(`${config.startDate}T00:00:00Z`)
  const endTime = Date.parse(`${config.endDate}T00:00:00Z`)
  const initialCapital = parseNumericValue(config.initialCapital)
  const tradingFee = parseNumericValue(config.tradingFee)

  if (!config.symbol) errors.symbol = 'Select an asset.'
  if (!strategy) errors.strategyId = 'Select a supported strategy.'
  if (!Number.isFinite(startTime)) errors.startDate = 'Enter a valid start date.'
  if (!Number.isFinite(endTime)) errors.endDate = 'Enter a valid end date.'
  if (Number.isFinite(startTime) && Number.isFinite(endTime) && startTime >= endTime) {
    errors.dateRange = 'Start date must be earlier than end date.'
  }
  if (!Number.isFinite(initialCapital) || initialCapital <= 0) {
    errors.initialCapital = 'Initial capital must be greater than zero.'
  }
  if (!Number.isFinite(tradingFee) || tradingFee < 0) {
    errors.tradingFee = 'Trading fee must be zero or greater.'
  }

  if (config.strategyId === 'ma-crossover') {
    if (!isIntegerAtLeast(config.shortMa, 2)) errors.shortMa = 'Enter a whole number of 2 or greater.'
    if (!isIntegerAtLeast(config.longMa, 3)) errors.longMa = 'Enter a whole number of 3 or greater.'
    if (!errors.shortMa && !errors.longMa && Number(config.shortMa) >= Number(config.longMa)) {
      errors.shortMa = 'Short MA must be smaller than Long MA.'
    }
  }

  if (config.strategyId === 'rsi') {
    const oversold = parseNumericValue(config.oversold)
    const overbought = parseNumericValue(config.overbought)
    if (!isIntegerAtLeast(config.rsiPeriod, 2)) errors.rsiPeriod = 'Enter a whole number of 2 or greater.'
    if (!Number.isFinite(oversold) || oversold < 0 || oversold > 100) {
      errors.oversold = 'Use a threshold from 0 to 100.'
    }
    if (!Number.isFinite(overbought) || overbought < 0 || overbought > 100) {
      errors.overbought = 'Use a threshold from 0 to 100.'
    }
    if (!errors.oversold && !errors.overbought && oversold >= overbought) {
      errors.oversold = 'Oversold must be smaller than Overbought.'
    }
  }

  if (config.strategyId === 'macd') {
    if (!isIntegerAtLeast(config.fastPeriod, 2)) errors.fastPeriod = 'Enter a whole number of 2 or greater.'
    if (!isIntegerAtLeast(config.slowPeriod, 3)) errors.slowPeriod = 'Enter a whole number of 3 or greater.'
    if (!isIntegerAtLeast(config.signalPeriod, 2)) errors.signalPeriod = 'Enter a whole number of 2 or greater.'
    if (!errors.fastPeriod && !errors.slowPeriod && Number(config.fastPeriod) >= Number(config.slowPeriod)) {
      errors.fastPeriod = 'MACD Fast period must be smaller than Slow period.'
    }
  }

  return errors
}

function hashString(value) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function createSeededRandom(seed) {
  let state = seed >>> 0
  return () => {
    state += 0x6d2b79f5
    let value = state
    value = Math.imul(value ^ (value >>> 15), value | 1)
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61)
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296
  }
}

function round(value, precision = 2) {
  const factor = 10 ** precision
  return Math.round((value + Number.EPSILON) * factor) / factor
}

function getStrategyReason(strategyId, action, config) {
  if (strategyId === 'rsi') {
    return action === 'Buy'
      ? `RSI moved below ${config.oversold}`
      : `RSI recovered toward ${config.overbought}`
  }

  if (strategyId === 'macd') {
    return action === 'Buy' ? 'DIF crossed above DEA' : 'DIF crossed below DEA'
  }

  return action === 'Buy'
    ? `MA${config.shortMa} crossed above MA${config.longMa}`
    : `MA${config.shortMa} crossed below MA${config.longMa}`
}

function createTradeHistory(config, asset, points, random) {
  const tradePointIndices = [3, 7, 11, 15, 20, 24, 29, 33].filter((index) => index < points.length)
  const finalBenchmarkValue = points.at(-1).benchmarkValue
  const initialCapital = Number(config.initialCapital)
  const tradingFee = Number(config.tradingFee)
  let lastBuyPrice = null

  return tradePointIndices.map((pointIndex, index) => {
    const point = points[pointIndex]
    const action = index % 2 === 0 ? 'Buy' : 'Sell'
    const marketRatio = point.benchmarkValue / finalBenchmarkValue
    const price = round(asset.currentPrice * marketRatio * (0.992 + random() * 0.016), 2)
    const quantity = round(Math.max(0.01, (initialCapital * 0.12) / price), 4)
    const returnPercent = action === 'Sell' && lastBuyPrice
      ? round(((price / lastBuyPrice) - 1) * 100 - tradingFee * 2, 2)
      : null

    if (action === 'Buy') lastBuyPrice = price

    return {
      id: `trade-${index + 1}`,
      date: point.date,
      action,
      price,
      quantity,
      tradeValue: round(price * quantity, 2),
      returnPercent,
      signalReason: getStrategyReason(config.strategyId, action, config),
    }
  })
}

function createResultSummary(metrics) {
  const comparisonGap = metrics.totalReturn - metrics.benchmarkReturn
  const comparison = comparisonGap >= 0
    ? `The strategy outperformed the buy-and-hold benchmark by ${Math.abs(comparisonGap).toFixed(2)} percentage points.`
    : `The strategy trailed the buy-and-hold benchmark by ${Math.abs(comparisonGap).toFixed(2)} percentage points.`

  const drawdownMagnitude = Math.abs(metrics.maximumDrawdown)
  const drawdownRisk = drawdownMagnitude <= 10
    ? `Maximum drawdown was ${drawdownMagnitude.toFixed(2)}%, indicating relatively contained downside in this simulation.`
    : drawdownMagnitude <= 20
      ? `Maximum drawdown was ${drawdownMagnitude.toFixed(2)}%, indicating moderate downside risk.`
      : `Maximum drawdown was ${drawdownMagnitude.toFixed(2)}%, indicating elevated downside risk.`

  const winRateAssessment = metrics.winRate >= 55 ? 'strong' : metrics.winRate >= 45 ? 'mixed' : 'weak'
  const sharpeAssessment = metrics.sharpeRatio >= 1 ? 'strong' : metrics.sharpeRatio >= 0.5 ? 'moderate' : 'weak'
  const quality = `The ${metrics.winRate.toFixed(2)}% win rate is ${winRateAssessment}, while the ${metrics.sharpeRatio.toFixed(2)} Sharpe ratio indicates ${sharpeAssessment} risk-adjusted performance.`

  return {
    comparison,
    drawdownRisk,
    quality,
    disclaimer: 'These simulated historical results are descriptive decision support, not a forecast or guaranteed financial advice.',
  }
}

export function createMockBacktestResult(config, asset, runAt = new Date()) {
  const strategy = backtestStrategies.find((item) => item.id === config.strategyId)
  const profile = strategyProfiles[config.strategyId] ?? strategyProfiles['ma-crossover']
  const startTime = Date.parse(`${config.startDate}T00:00:00Z`)
  const endTime = Date.parse(`${config.endDate}T00:00:00Z`)
  const durationDays = Math.max((endTime - startTime) / 86400000, 1)
  const initialCapital = Number(config.initialCapital)
  const feeRate = Number(config.tradingFee) / 100
  const seed = hashString(JSON.stringify(config))
  const random = createSeededRandom(seed)
  const pointCount = 37
  const assetDrift = ((hashString(asset.symbol) % 7) - 3) * 0.00015
  let portfolioValue = initialCapital
  let benchmarkValue = initialCapital
  let runningPeak = initialCapital
  const stepReturns = []
  const points = []

  for (let index = 0; index < pointCount; index += 1) {
    if (index > 0) {
      const marketShock = (random() - 0.5) * 0.027
      const benchmarkStepReturn = 0.0022 + assetDrift + marketShock
      const strategyNoise = (random() - 0.5) * profile.noise
      const timingWave = Math.sin((index + (seed % 9)) * 0.72) * 0.0015
      const feeImpact = index % 5 === 0 ? feeRate * 0.35 : 0
      const portfolioStepReturn = benchmarkStepReturn * profile.beta
        + profile.alpha
        + strategyNoise
        + timingWave
        - feeImpact

      benchmarkValue = Math.max(initialCapital * 0.55, benchmarkValue * (1 + benchmarkStepReturn))
      portfolioValue = Math.max(initialCapital * 0.55, portfolioValue * (1 + portfolioStepReturn))
      runningPeak = Math.max(runningPeak, portfolioValue)
      stepReturns.push(portfolioStepReturn)
    }

    const pointTime = startTime + ((endTime - startTime) * index) / (pointCount - 1)
    points.push({
      date: new Date(pointTime).toISOString().slice(0, 10),
      portfolioValue: round(portfolioValue, 2),
      benchmarkValue: round(benchmarkValue, 2),
      drawdown: round(((portfolioValue / runningPeak) - 1) * 100, 4),
    })
  }

  const trades = createTradeHistory(config, asset, points, random)
  const completedTrades = trades.filter((trade) => trade.action === 'Sell' && Number.isFinite(trade.returnPercent))
  const winningTrades = completedTrades.filter((trade) => trade.returnPercent > 0).length
  const finalPoint = points.at(-1)
  const totalReturn = ((finalPoint.portfolioValue / initialCapital) - 1) * 100
  const benchmarkReturn = ((finalPoint.benchmarkValue / initialCapital) - 1) * 100
  const annualisedReturn = (Math.pow(finalPoint.portfolioValue / initialCapital, 365 / durationDays) - 1) * 100
  const maximumDrawdown = Math.min(...points.map((point) => point.drawdown))
  const meanReturn = stepReturns.reduce((total, value) => total + value, 0) / Math.max(stepReturns.length, 1)
  const variance = stepReturns.reduce((total, value) => total + (value - meanReturn) ** 2, 0)
    / Math.max(stepReturns.length - 1, 1)
  const standardDeviation = Math.sqrt(variance)
  const periodsPerYear = (365 / durationDays) * Math.max(stepReturns.length, 1)
  const sharpeRatio = standardDeviation ? (meanReturn / standardDeviation) * Math.sqrt(periodsPerYear) : 0
  const metrics = {
    totalReturn: round(totalReturn, 4),
    annualisedReturn: round(annualisedReturn, 4),
    maximumDrawdown: round(maximumDrawdown, 4),
    winRate: completedTrades.length ? round((winningTrades / completedTrades.length) * 100, 4) : 0,
    sharpeRatio: round(sharpeRatio, 4),
    numberOfTrades: trades.length,
    benchmarkReturn: round(benchmarkReturn, 4),
  }

  return {
    schemaVersion: 1,
    id: `backtest-${runAt.getTime()}-${seed.toString(36)}`,
    runAt: runAt.toISOString(),
    config: { ...config },
    asset: {
      symbol: asset.symbol,
      name: asset.asset,
      type: asset.type,
    },
    strategy: {
      id: strategy.id,
      label: strategy.label,
    },
    metrics,
    points,
    trades,
    summary: createResultSummary(metrics),
  }
}

function isFiniteMetricSet(metrics) {
  const metricKeys = [
    'totalReturn',
    'annualisedReturn',
    'maximumDrawdown',
    'winRate',
    'sharpeRatio',
    'numberOfTrades',
    'benchmarkReturn',
  ]
  return metrics && metricKeys.every((key) => Number.isFinite(metrics[key]))
}

export function sanitizeBacktestHistory(value, knownSymbols = []) {
  if (!Array.isArray(value)) return []
  const knownSymbolSet = new Set(knownSymbols)

  return [...value]
    .filter((result) => (
      result?.schemaVersion === 1
      && typeof result.id === 'string'
      && Number.isFinite(Date.parse(result.runAt))
      && result.config
      && Object.keys(validateBacktestConfig(result.config)).length === 0
      && typeof result.asset?.symbol === 'string'
      && (!knownSymbolSet.size || knownSymbolSet.has(result.asset.symbol))
      && typeof result.strategy?.label === 'string'
      && isFiniteMetricSet(result.metrics)
      && Array.isArray(result.points)
      && result.points.length > 1
      && Array.isArray(result.trades)
      && result.summary
    ))
    .sort((left, right) => Date.parse(right.runAt) - Date.parse(left.runAt))
    .slice(0, backtestHistoryLimit)
}
