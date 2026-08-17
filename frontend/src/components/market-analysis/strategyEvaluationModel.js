const strategyLabels = {
  trend_following: 'Trend Following',
  mean_reversion: 'Mean Reversion',
  risk_off: 'Risk Off',
}

const strategyModeLabels = {
  active: 'Active',
  defensive: 'Defensive',
}

const executionModeLabels = {
  long_only: 'Long Only',
}

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function finiteNumber(value) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function normalizedSymbol(value) {
  return String(value ?? '').trim().toUpperCase()
}

function displayLabel(mapping, value) {
  return mapping[value] ?? 'N/A'
}

function capitalize(value) {
  return String(value).replace(/^./, (letter) => letter.toUpperCase())
}

export function formatStrategyLabel(strategy) {
  return displayLabel(strategyLabels, strategy)
}

export function formatStrategyModeLabel(strategyMode) {
  return displayLabel(strategyModeLabels, strategyMode)
}

export function formatExecutionModeLabel(executionMode) {
  return displayLabel(executionModeLabels, executionMode)
}

export function formatAllowNewLong(value) {
  if (value === true) return 'Yes'
  if (value === false) return 'No'
  return 'N/A'
}

export function formatSelectionConfidence(confidence) {
  if (confidence === null || confidence === undefined || confidence === '') return 'N/A'
  return capitalize(confidence)
}

export function formatEvaluationPercent(value, { digits = 2, signed = false } = {}) {
  const number = finiteNumber(value)
  if (number === null) return 'N/A'
  const prefix = signed && number > 0 ? '+' : ''
  return `${prefix}${number.toFixed(digits)}%`
}

export function formatEvaluationMoney(value) {
  const number = finiteNumber(value)
  return number === null ? 'N/A' : currencyFormatter.format(number)
}

export function formatTradeCount(value) {
  const number = finiteNumber(value)
  if (number === null) return 'N/A'
  return String(Math.trunc(number))
}

export function formatUnavailableReason(reason) {
  if (!reason) return 'Historical evaluation is unavailable for the selected strategy.'
  return String(reason)
    .replaceAll('_', ' ')
    .replace(/^./, (letter) => letter.toUpperCase())
    .replace(/\.?$/, '.')
}

export function strategyEvaluationResponseMatchesSymbol(response, expectedSymbol) {
  return normalizedSymbol(response?.symbol) === normalizedSymbol(expectedSymbol)
}

export function isCurrentStrategyEvaluationRequest(currentRequestId, responseRequestId) {
  return currentRequestId === responseRequestId
}

export function getStrategyEvaluationPanelState(requestState, selectedSymbol) {
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

function normalizeReasons(reason) {
  return Array.isArray(reason)
    ? reason.filter((item) => typeof item === 'string' && item.trim())
    : []
}

export function normalizeStrategyEvaluation(response, expectedSymbol) {
  if (!strategyEvaluationResponseMatchesSymbol(response, expectedSymbol)) {
    throw new Error('Strategy evaluation response did not match the selected stock.')
  }

  return {
    symbol: normalizedSymbol(response.symbol),
    selectionAvailable: response.strategy_selection_available === true,
    marketRegime: response.market_regime ?? null,
    marketRegimeUnavailableReason: response.market_regime_unavailable_reason ?? null,
    selectedStrategy: response.selected_strategy ?? null,
    strategyLabel: formatStrategyLabel(response.selected_strategy),
    strategyMode: response.strategy_mode ?? null,
    strategyModeLabel: formatStrategyModeLabel(response.strategy_mode),
    executionMode: response.execution_mode ?? null,
    executionModeLabel: formatExecutionModeLabel(response.execution_mode),
    allowNewLong: response.allow_new_long ?? null,
    riskOff: response.risk_off === true,
    selectionConfidence: formatSelectionConfidence(
      response.selection_confidence ?? response.regime_confidence,
    ),
    reason: normalizeReasons(response.reason),
    evaluationAvailable: response.evaluation_available === true,
    evaluationStatus: response.evaluation_status ?? null,
    evaluationUnavailableReason: response.evaluation_unavailable_reason ?? null,
    evaluationStrategy: response.evaluation_strategy ?? null,
    metrics: {
      initialCapital: finiteNumber(response.initial_capital),
      finalEquity: finiteNumber(response.final_equity),
      totalReturn: finiteNumber(response.total_return),
      maximumDrawdown: finiteNumber(response.maximum_drawdown),
      annualizedVolatility: finiteNumber(response.annualized_volatility),
      totalFees: finiteNumber(response.total_fees),
      executedOrderCount: finiteNumber(response.executed_order_count),
    },
    evaluationWindow: response.evaluation_window ?? null,
    dataSource: response.data_source ?? null,
    strategyParameters: response.strategy_parameters ?? null,
    equityCurve: Array.isArray(response.equity_curve) ? response.equity_curve : [],
    drawdownCurve: Array.isArray(response.drawdown_curve) ? response.drawdown_curve : [],
    trades: Array.isArray(response.trades) ? response.trades : [],
  }
}
