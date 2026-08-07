export const backtestHistoryStorageKey = 'aiquantification.backtest.history'
export const selectedBacktestStorageKey = 'aiquantification.backtest.selectedBacktestId'
export const legacySelectedBacktestStorageKey = 'selectedBacktestId'
export const backtestHistoryLimit = 8
export const backtestResultSchemaVersion = 5

export const backtestStrategies = [
  {
    id: 'market-regime-core-swing',
    label: 'Market-Regime Core and Swing Strategy',
    description: 'Uses benchmark regime, ATR-sized Core exposure and independent pullback Swing cycles.',
    parameters: [
      { key: 'coreFastMa', label: 'Core fast MA', min: 1, step: 1 },
      { key: 'coreSlowMa', label: 'Core slow MA', min: 1, step: 1 },
      { key: 'coreRiskPercent', label: 'Core Risk (%)', min: 0.1, max: 5, step: 0.1 },
      { key: 'coreAtrMultiplier', label: 'Core ATR Multiplier', min: 0.5, max: 8, step: 0.1 },
      { key: 'maxCoreExposurePercent', label: 'Max Core Exposure (%)', min: 10, max: 100, step: 5 },
      { key: 'swingRiskPercent', label: 'Swing Risk (%)', min: 0.1, max: 2, step: 0.1 },
      { key: 'swingAtrMultiplier', label: 'Swing ATR Multiplier', min: 0.5, max: 5, step: 0.1 },
      { key: 'swingRsiLookback', label: 'Swing RSI Lookback', min: 1, max: 60, step: 1 },
      { key: 'swingRsiEntryLevel', label: 'Swing RSI Entry Level', min: 1, max: 99, step: 1 },
      { key: 'swingRsiExitLevel', label: 'Swing RSI Exit Level', min: 1, max: 99, step: 1 },
      {
        key: 'swingAverageType',
        label: 'Swing Trend Average',
        type: 'select',
        options: [
          { value: 'EMA10', label: 'EMA10' },
          { value: 'SMA10', label: 'SMA10' },
        ],
      },
      { key: 'swingCooldownDays', label: 'Swing Cooldown Days', min: 0, max: 30, step: 1 },
    ],
  },
]

export const defaultBacktestConfig = {
  symbol: 'AAPL',
  benchmarkSymbol: 'SPY',
  strategyId: 'market-regime-core-swing',
  startDate: '2025-07-01',
  endDate: '2026-06-30',
  initialCapital: '10000',
  transactionFee: '1.00',
  coreFastMa: '20',
  coreSlowMa: '60',
  coreRiskPercent: '2',
  coreAtrMultiplier: '2.5',
  maxCoreExposurePercent: '80',
  swingRiskPercent: '1',
  swingAtrMultiplier: '1.2',
  swingRsiLookback: '10',
  swingRsiEntryLevel: '45',
  swingRsiExitLevel: '60',
  swingAverageType: 'EMA10',
  swingCooldownDays: '2',
}

function parseNumericValue(value) {
  if (value === null || value === undefined || String(value).trim() === '') return Number.NaN
  return Number(value)
}

function isIntegerAtLeast(value, minimum) {
  const parsed = parseNumericValue(value)
  return Number.isInteger(parsed) && parsed >= minimum
}

function validateRange(value, label, minimum, maximum, unit = '') {
  const parsed = parseNumericValue(value)
  if (!Number.isFinite(parsed) || parsed < minimum || parsed > maximum) {
    return `${label} must be between ${minimum}${unit} and ${maximum}${unit}.`
  }
  return ''
}

export function validateBacktestConfig(config) {
  const errors = {}
  const strategy = backtestStrategies.find((item) => item.id === config.strategyId)
  const startTime = Date.parse(`${config.startDate}T00:00:00Z`)
  const endTime = Date.parse(`${config.endDate}T00:00:00Z`)
  const initialCapital = parseNumericValue(config.initialCapital)
  const transactionFee = parseNumericValue(config.transactionFee)

  if (!config.symbol) errors.symbol = 'Select an asset.'
  if (!config.benchmarkSymbol) errors.benchmarkSymbol = 'Select a benchmark.'
  if (!strategy) errors.strategyId = 'Select a supported strategy.'
  if (!Number.isFinite(startTime)) errors.startDate = 'Enter a valid start date.'
  if (!Number.isFinite(endTime)) errors.endDate = 'Enter a valid end date.'
  if (Number.isFinite(startTime) && Number.isFinite(endTime) && startTime >= endTime) {
    errors.dateRange = 'Start date must be earlier than end date.'
  }
  if (!Number.isFinite(initialCapital) || initialCapital <= 0) {
    errors.initialCapital = 'Initial capital must be greater than zero.'
  }
  if (!Number.isFinite(transactionFee) || transactionFee < 0) {
    errors.transactionFee = 'Transaction fee must be zero or greater.'
  }
  if (!isIntegerAtLeast(config.coreFastMa, 1)) errors.coreFastMa = 'Enter a positive whole number.'
  if (!isIntegerAtLeast(config.coreSlowMa, 1)) errors.coreSlowMa = 'Enter a positive whole number.'
  if (!errors.coreFastMa && !errors.coreSlowMa && Number(config.coreFastMa) >= Number(config.coreSlowMa)) {
    errors.coreFastMa = 'Core fast MA must be smaller than Core slow MA.'
  }

  const coreRiskError = validateRange(config.coreRiskPercent, 'Core Risk', 0.1, 5, '%')
  const maxCoreExposureError = validateRange(config.maxCoreExposurePercent, 'Max Core Exposure', 10, 100, '%')
  const swingRiskError = validateRange(config.swingRiskPercent, 'Swing Risk', 0.1, 2, '%')
  const coreAtrError = validateRange(config.coreAtrMultiplier, 'Core ATR Multiplier', 0.5, 8)
  const swingAtrError = validateRange(config.swingAtrMultiplier, 'Swing ATR Multiplier', 0.5, 5)
  if (coreRiskError) errors.coreRiskPercent = coreRiskError
  if (maxCoreExposureError) errors.maxCoreExposurePercent = maxCoreExposureError
  if (swingRiskError) errors.swingRiskPercent = swingRiskError
  if (coreAtrError) errors.coreAtrMultiplier = coreAtrError
  if (swingAtrError) errors.swingAtrMultiplier = swingAtrError

  const swingRsiLookback = parseNumericValue(config.swingRsiLookback)
  const swingRsiEntryLevel = parseNumericValue(config.swingRsiEntryLevel)
  const swingRsiExitLevel = parseNumericValue(config.swingRsiExitLevel)
  const swingCooldownDays = parseNumericValue(config.swingCooldownDays)
  if (!Number.isInteger(swingRsiLookback) || swingRsiLookback < 1 || swingRsiLookback > 60) {
    errors.swingRsiLookback = 'Swing RSI Lookback must be a whole number between 1 and 60.'
  }
  if (!Number.isFinite(swingRsiEntryLevel) || swingRsiEntryLevel < 1 || swingRsiEntryLevel > 99) {
    errors.swingRsiEntryLevel = 'Swing RSI Entry Level must be between 1 and 99.'
  }
  if (!Number.isFinite(swingRsiExitLevel) || swingRsiExitLevel < 1 || swingRsiExitLevel > 99) {
    errors.swingRsiExitLevel = 'Swing RSI Exit Level must be between 1 and 99.'
  }
  if (!errors.swingRsiEntryLevel && !errors.swingRsiExitLevel && swingRsiEntryLevel >= swingRsiExitLevel) {
    errors.swingRsiEntryLevel = 'Swing RSI Entry Level must be lower than Swing RSI Exit Level.'
  }
  if (!Number.isInteger(swingCooldownDays) || swingCooldownDays < 0 || swingCooldownDays > 30) {
    errors.swingCooldownDays = 'Swing Cooldown Days must be a whole number between 0 and 30.'
  }
  if (!['EMA10', 'SMA10'].includes(config.swingAverageType)) {
    errors.swingAverageType = 'Select EMA10 or SMA10.'
  }

  return errors
}

export function buildBacktestRequestPayload(config, securityId) {
  return {
    security: securityId,
    benchmark: config.benchmarkSymbol,
    start_date: config.startDate,
    end_date: config.endDate,
    initial_capital: Number(config.initialCapital),
    transaction_fee: Number(config.transactionFee),
    core_fast_ma: Number(config.coreFastMa),
    core_slow_ma: Number(config.coreSlowMa),
    core_risk_fraction: Number(config.coreRiskPercent) / 100,
    core_atr_multiplier: Number(config.coreAtrMultiplier),
    max_core_exposure: Number(config.maxCoreExposurePercent) / 100,
    swing_risk_fraction: Number(config.swingRiskPercent) / 100,
    swing_atr_multiplier: Number(config.swingAtrMultiplier),
    swing_rsi_lookback: Number(config.swingRsiLookback),
    swing_rsi_entry_level: Number(config.swingRsiEntryLevel),
    swing_rsi_exit_level: Number(config.swingRsiExitLevel),
    swing_trend_average: config.swingAverageType,
    swing_cooldown_days: Number(config.swingCooldownDays),
  }
}

export function createBacktestRunRequest(config, asset) {
  const configSnapshot = { ...config }
  const assetSnapshot = asset ? { ...asset } : null
  return {
    config: configSnapshot,
    asset: assetSnapshot,
    payload: buildBacktestRequestPayload(configSnapshot, assetSnapshot?.id),
  }
}

export function buildBacktestFailureState(request, error) {
  return {
    currentResult: null,
    error: {
      assetSymbol: request?.asset?.symbol || request?.config?.symbol || 'selected asset',
      benchmarkSymbol: request?.config?.benchmarkSymbol || 'SPY',
      message: error?.message || 'Backtest request failed.',
      details: error?.data || null,
      request,
    },
  }
}

function parseNumber(value, fallback = 0) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function parseNullableNumber(value) {
  return value === null || value === undefined ? null : parseNumber(value, null)
}

function formatPercentInput(fraction, fallbackPercent) {
  const parsed = Number(fraction)
  if (!Number.isFinite(parsed)) return String(fallbackPercent)
  return String(Number((parsed * 100).toFixed(4)))
}

function formatMultiplierInput(value, fallback) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return String(fallback)
  const rounded = Number(parsed.toFixed(2))
  return Number.isInteger(rounded) ? rounded.toFixed(1) : String(rounded)
}

function formatConfigFromResponse(response, fallbackConfig) {
  const parameters = response?.strategy_parameters || {}
  const coreRiskFraction = parameters.core_risk_fraction ?? parameters.core_risk_percentage
  const swingRiskFraction = parameters.swing_risk_fraction ?? parameters.swing_risk_percentage
  return {
    ...defaultBacktestConfig,
    ...fallbackConfig,
    symbol: response?.security?.symbol ?? fallbackConfig.symbol ?? defaultBacktestConfig.symbol,
    benchmarkSymbol: response?.benchmark?.symbol
      ?? parameters.benchmark
      ?? fallbackConfig.benchmarkSymbol
      ?? defaultBacktestConfig.benchmarkSymbol,
    strategyId: 'market-regime-core-swing',
    startDate: response?.data_source?.requested_start_date ?? fallbackConfig.startDate,
    endDate: response?.data_source?.requested_end_date ?? fallbackConfig.endDate,
    initialCapital: String(response?.initial_capital ?? fallbackConfig.initialCapital ?? defaultBacktestConfig.initialCapital),
    transactionFee: String(parameters.transaction_fee ?? fallbackConfig.transactionFee ?? defaultBacktestConfig.transactionFee),
    coreFastMa: String(parameters.core_fast_ma ?? fallbackConfig.coreFastMa ?? defaultBacktestConfig.coreFastMa),
    coreSlowMa: String(parameters.core_slow_ma ?? fallbackConfig.coreSlowMa ?? defaultBacktestConfig.coreSlowMa),
    coreRiskPercent: formatPercentInput(coreRiskFraction, fallbackConfig.coreRiskPercent ?? defaultBacktestConfig.coreRiskPercent),
    coreAtrMultiplier: formatMultiplierInput(parameters.core_atr_multiplier, fallbackConfig.coreAtrMultiplier ?? defaultBacktestConfig.coreAtrMultiplier),
    maxCoreExposurePercent: formatPercentInput(parameters.max_core_exposure, fallbackConfig.maxCoreExposurePercent ?? defaultBacktestConfig.maxCoreExposurePercent),
    swingRiskPercent: formatPercentInput(swingRiskFraction, fallbackConfig.swingRiskPercent ?? defaultBacktestConfig.swingRiskPercent),
    swingAtrMultiplier: formatMultiplierInput(parameters.swing_atr_multiplier, fallbackConfig.swingAtrMultiplier ?? defaultBacktestConfig.swingAtrMultiplier),
    swingRsiLookback: String(parameters.swing_rsi_lookback ?? fallbackConfig.swingRsiLookback ?? defaultBacktestConfig.swingRsiLookback),
    swingRsiEntryLevel: String(Number(parameters.swing_rsi_entry_level ?? fallbackConfig.swingRsiEntryLevel ?? defaultBacktestConfig.swingRsiEntryLevel)),
    swingRsiExitLevel: String(Number(parameters.swing_rsi_exit_level ?? fallbackConfig.swingRsiExitLevel ?? defaultBacktestConfig.swingRsiExitLevel)),
    swingAverageType: parameters.swing_trend_average
      ?? parameters.swing_average_type
      ?? fallbackConfig.swingAverageType
      ?? defaultBacktestConfig.swingAverageType,
    swingCooldownDays: String(parameters.swing_cooldown_days ?? fallbackConfig.swingCooldownDays ?? defaultBacktestConfig.swingCooldownDays),
  }
}

export function normalizeBacktestResult(response, fallbackConfig = {}) {
  const drawdownByDate = new Map(
    (Array.isArray(response?.drawdown_curve) ? response.drawdown_curve : [])
      .map((point) => [point.date, parseNumber(point.drawdown)]),
  )
  const points = (Array.isArray(response?.equity_curve) ? response.equity_curve : [])
    .filter((point) => typeof point?.date === 'string')
    .map((point) => ({
      date: point.date,
      close: parseNullableNumber(point.close),
      portfolioValue: parseNumber(point.total_equity),
      cash: parseNumber(point.cash),
      holdingsValue: parseNumber(point.holdings_value),
      ma10: parseNullableNumber(point.ma10),
      ema10: parseNullableNumber(point.ema10),
      swingAverage: parseNullableNumber(point.swing_average ?? point.ema10 ?? point.ma10),
      swingAverageType: point.swing_average_type || 'SMA10',
      ma20: parseNullableNumber(point.ma20),
      ma60: parseNullableNumber(point.ma60),
      rsi14: parseNullableNumber(point.rsi14),
      atr14: parseNullableNumber(point.atr14),
      bollingerUpper: parseNullableNumber(point.bollinger_upper),
      marketRegime: point.market_regime || 'NEUTRAL',
      coreQuantity: parseNumber(point.core_quantity),
      coreAverageCost: parseNumber(point.core_average_cost),
      swingQuantity: parseNumber(point.swing_quantity),
      swingAverageCost: parseNumber(point.swing_average_cost),
      coreExposure: parseNumber(point.core_exposure),
      swingExposure: parseNumber(point.swing_exposure),
      totalExposure: parseNumber(point.total_exposure),
      drawdown: drawdownByDate.get(point.date) ?? parseNumber(point.drawdown),
    }))

  const trades = (Array.isArray(response?.trades) ? response.trades : [])
    .map((trade, index) => {
      const quantity = parseNumber(trade.quantity)
      const executionPrice = parseNumber(trade.execution_price)
      return {
        id: trade.id ?? `trade-${index + 1}`,
        positionLayer: trade.position_layer,
        reason: trade.reason,
        signalDate: trade.signal_date,
        executionDate: trade.execution_date,
        date: trade.execution_date,
        action: trade.type === 'SELL' ? 'Sell' : 'Buy',
        type: trade.type,
        price: executionPrice,
        quantity,
        tradeValue: quantity * executionPrice,
        fee: parseNumber(trade.fee),
        cashAfter: parseNumber(trade.cash_after),
        coreQuantityAfter: parseNumber(trade.core_quantity_after),
        swingQuantityAfter: parseNumber(trade.swing_quantity_after),
        totalQuantityAfter: parseNumber(trade.total_quantity_after),
        realizedProfitLoss: parseNumber(trade.realized_profit_loss),
        equityBefore: parseNullableNumber(trade.equity_before),
        riskFraction: parseNullableNumber(trade.risk_fraction),
        riskAmount: parseNullableNumber(trade.risk_amount),
        atr: parseNullableNumber(trade.atr),
        stopDistance: parseNullableNumber(trade.stop_distance),
        rawQuantity: parseNullableNumber(trade.raw_quantity),
        affordableQuantity: parseNullableNumber(trade.affordable_quantity),
        exposureCappedQuantity: parseNullableNumber(trade.exposure_capped_quantity),
        finalQuantity: parseNumber(trade.final_quantity ?? trade.quantity),
        rawExposure: parseNullableNumber(trade.raw_exposure),
        finalExposure: parseNullableNumber(trade.final_exposure),
        exposureCapApplied: Boolean(trade.exposure_cap_applied),
        cashCapApplied: Boolean(trade.cash_cap_applied),
      }
    })

  const config = formatConfigFromResponse(response, fallbackConfig)
  const strategy = backtestStrategies[0]
  const parameters = response?.strategy_parameters || {}
  const comparisons = (Array.isArray(response?.comparisons) ? response.comparisons : []).map((item) => ({
    strategy: item.strategy,
    strategyId: item.strategy_id,
    totalReturn: parseNumber(item.total_return),
    finalEquity: parseNumber(item.final_equity),
    maximumDrawdown: parseNumber(item.maximum_drawdown),
    annualizedVolatility: parseNumber(item.annualized_volatility),
    totalFees: parseNumber(item.total_fees),
    executedOrders: Number(item.executed_orders) || 0,
  }))

  return {
    schemaVersion: backtestResultSchemaVersion,
    id: response?.id ?? `backtest-${Date.now()}`,
    runAt: response?.run_at ?? new Date().toISOString(),
    config,
    asset: {
      id: response?.security?.id,
      symbol: response?.security?.symbol ?? config.symbol,
      name: response?.security?.name ?? config.symbol,
      type: response?.security?.asset_type === 'ETF' ? 'ETF' : 'Stock',
      exchange: response?.security?.exchange ?? '',
      currency: response?.security?.currency ?? 'USD',
    },
    benchmark: response?.benchmark || { symbol: config.benchmarkSymbol },
    strategy: { id: strategy.id, label: strategy.label },
    parametersUsed: {
      coreFastMa: Number(parameters.core_fast_ma),
      coreSlowMa: Number(parameters.core_slow_ma),
      coreRiskPercent: parseNumber(parameters.core_risk_fraction ?? parameters.core_risk_percentage) * 100,
      coreAtrMultiplier: parseNumber(parameters.core_atr_multiplier),
      maxCoreExposurePercent: parseNumber(parameters.max_core_exposure) * 100,
      swingRiskPercent: parseNumber(parameters.swing_risk_fraction ?? parameters.swing_risk_percentage) * 100,
      swingAtrMultiplier: parseNumber(parameters.swing_atr_multiplier),
      swingRsiLookback: Number(parameters.swing_rsi_lookback),
      swingRsiEntryLevel: parseNumber(parameters.swing_rsi_entry_level),
      swingRsiExitLevel: parseNumber(parameters.swing_rsi_exit_level),
      swingAverageType: parameters.swing_trend_average || parameters.swing_average_type || 'EMA10',
      swingCooldownDays: Number(parameters.swing_cooldown_days),
    },
    metrics: {
      totalReturn: parseNumber(response?.total_return),
      finalEquity: parseNumber(response?.final_equity),
      maximumDrawdown: parseNumber(response?.maximum_drawdown),
      annualizedVolatility: parseNumber(response?.annualized_volatility),
      executedOrderCount: Number(response?.executed_order_count) || 0,
      totalFees: parseNumber(response?.total_fees),
    },
    coreMetrics: {
      returnContribution: parseNumber(response?.core_return_contribution),
      realizedProfitLoss: parseNumber(response?.core_realized_profit_loss),
      unrealizedProfitLoss: parseNumber(response?.core_unrealized_profit_loss),
      holdingDays: Number(response?.core_holding_days) || 0,
      entryCount: Number(response?.core_entry_count) || 0,
      exitCount: Number(response?.core_exit_count) || 0,
    },
    swingMetrics: {
      returnContribution: parseNumber(response?.swing_return_contribution),
      realizedProfitLoss: parseNumber(response?.swing_realized_profit_loss),
      unrealizedProfitLoss: parseNumber(response?.swing_unrealized_profit_loss),
      cycleCount: Number(response?.swing_cycle_count) || 0,
      entryCount: Number(response?.swing_entry_count) || 0,
      exitCount: Number(response?.swing_exit_count) || 0,
      averageDaysPerCycle: parseNumber(response?.average_days_per_swing_cycle),
      profitableCycleCount: Number(response?.profitable_swing_cycle_count) || 0,
      winRate: parseNumber(response?.swing_win_rate),
      averageReturn: parseNumber(response?.average_swing_return),
      fees: parseNumber(response?.swing_total_fees ?? response?.swing_fees),
      turnover: parseNumber(response?.swing_turnover),
    },
    swingSignalDiagnostics: response?.swing_signal_diagnostics || {
      eligible_core_days: 0,
      market_bear_days: 0,
      rsi_pullback_detected_days: 0,
      rsi_upward_cross_days: 0,
      close_above_trend_average_days: 0,
      cooldown_blocked_days: 0,
      swing_entry_signal_count: 0,
      swing_exit_signal_count: 0,
      primary_block_reason_counts: {},
    },
    points,
    trades,
    comparisons,
    dataSource: response?.data_source || {},
    summary: response?.summary || {},
    signalMessage: response?.signal_message || '',
  }
}

function isFiniteMetricSet(metrics) {
  const metricKeys = [
    'totalReturn',
    'finalEquity',
    'maximumDrawdown',
    'annualizedVolatility',
    'executedOrderCount',
    'totalFees',
  ]
  return metrics && metricKeys.every((key) => Number.isFinite(metrics[key]))
}

function migrateStoredResult(result) {
  if (![3, 4].includes(result?.schemaVersion)) return result
  const oldConfig = result.config || {}
  const percentageConfig = result.schemaVersion === 3
    ? {
        ...oldConfig,
        coreRiskPercent: formatPercentInput(oldConfig.coreRiskPercentage, '1'),
        coreAtrMultiplier: formatMultiplierInput(oldConfig.coreAtrMultiplier, '2.0'),
        maxCoreExposurePercent: formatPercentInput(oldConfig.maxCoreExposure, '70'),
        swingRiskPercent: formatPercentInput(oldConfig.swingRiskPercentage, '0.5'),
        swingAtrMultiplier: formatMultiplierInput(oldConfig.swingAtrMultiplier, '1.5'),
      }
    : oldConfig
  const config = {
    ...defaultBacktestConfig,
    ...percentageConfig,
    swingRsiLookback: '5',
    swingRsiEntryLevel: '40',
    swingRsiExitLevel: '65',
    swingAverageType: 'SMA10',
    swingCooldownDays: '0',
  }
  delete config.coreRiskPercentage
  delete config.maxCoreExposure
  delete config.swingRiskPercentage
  return {
    ...result,
    schemaVersion: backtestResultSchemaVersion,
    config,
    parametersUsed: {
      ...(result.parametersUsed || {}),
      coreFastMa: Number(config.coreFastMa),
      coreSlowMa: Number(config.coreSlowMa),
      coreRiskPercent: Number(config.coreRiskPercent),
      coreAtrMultiplier: Number(config.coreAtrMultiplier),
      maxCoreExposurePercent: Number(config.maxCoreExposurePercent),
      swingRiskPercent: Number(config.swingRiskPercent),
      swingAtrMultiplier: Number(config.swingAtrMultiplier),
      swingRsiLookback: 5,
      swingRsiEntryLevel: 40,
      swingRsiExitLevel: 65,
      swingAverageType: 'SMA10',
      swingCooldownDays: 0,
    },
    points: (Array.isArray(result.points) ? result.points : []).map((point) => ({
      ...point,
      swingAverage: point.swingAverage ?? point.ma10 ?? null,
      swingAverageType: point.swingAverageType || 'SMA10',
    })),
    signalMessage: result.signalMessage || (
      Array.isArray(result.trades) && result.trades.length === 0
        ? 'No qualifying Core or Swing signals under the selected parameters.'
        : ''
    ),
  }
}

export function sanitizeBacktestHistory(value) {
  if (!Array.isArray(value)) return []

  return [...value]
    .map(migrateStoredResult)
    .filter((result) => (
      result?.schemaVersion === backtestResultSchemaVersion
      && typeof result.id === 'string'
      && Number.isFinite(Date.parse(result.runAt))
      && result.config
      && Object.keys(validateBacktestConfig(result.config)).length === 0
      && typeof result.asset?.symbol === 'string'
      && typeof result.strategy?.label === 'string'
      && isFiniteMetricSet(result.metrics)
      && Array.isArray(result.points)
      && result.points.length > 0
      && Array.isArray(result.trades)
      && Array.isArray(result.comparisons)
    ))
    .sort((left, right) => Date.parse(right.runAt) - Date.parse(left.runAt))
    .slice(0, backtestHistoryLimit)
}
