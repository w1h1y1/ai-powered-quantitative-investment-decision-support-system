import assert from 'node:assert/strict'
import test from 'node:test'
import {
  formatAllowNewLong,
  formatEvaluationMoney,
  formatEvaluationPercent,
  formatExecutionModeLabel,
  formatStrategyLabel,
  formatStrategyModeLabel,
  formatTradeCount,
  formatUnavailableReason,
  getStrategyEvaluationPanelState,
  isCurrentStrategyEvaluationRequest,
  normalizeStrategyEvaluation,
  strategyEvaluationResponseMatchesSymbol,
} from './strategyEvaluationModel.js'

function meanReversionResponse() {
  return {
    symbol: 'JPM',
    strategy_selection_available: true,
    market_regime: 'sideways_range',
    selected_strategy: 'mean_reversion',
    strategy_mode: 'active',
    execution_mode: 'long_only',
    allow_new_long: true,
    risk_off: false,
    selection_confidence: 'high',
    reason: [
      'The current market regime is Sideways / Range.',
      'Mean Reversion is preferred under the current regime.',
    ],
    evaluation_available: true,
    evaluation_status: 'completed',
    evaluation_unavailable_reason: null,
    evaluation_strategy: 'mean_reversion',
    initial_capital: '10000.000000',
    final_equity: '10123.450000',
    total_return: '12.345678',
    maximum_drawdown: '8.123456',
    annualized_volatility: '15.250000',
    total_fees: '2.000000',
    executed_order_count: 3,
    equity_curve: [{ date: '2026-08-13', total_equity: '10000.000000' }],
    drawdown_curve: [{ date: '2026-08-13', drawdown: '0.000000' }],
    trades: [],
    strategy_parameters: { strategy: 'Independent Mean Reversion v1' },
    evaluation_window: { start_date: '2025-08-14', end_date: '2026-08-13' },
    data_source: { source: 'database_cache' },
  }
}

function riskOffResponse() {
  return {
    symbol: 'AAPL',
    strategy_selection_available: true,
    market_regime: 'high_volatility',
    selected_strategy: 'risk_off',
    strategy_mode: 'defensive',
    execution_mode: 'long_only',
    allow_new_long: false,
    risk_off: true,
    selection_confidence: 'high',
    reason: [
      'The current market regime is High Volatility.',
      'Risk control takes priority over active strategy deployment.',
    ],
    evaluation_available: false,
    evaluation_status: 'not_applicable',
    evaluation_unavailable_reason: 'Risk-Off is a defensive state rather than an active trading strategy.',
    evaluation_strategy: null,
    initial_capital: null,
    final_equity: null,
    total_return: null,
    maximum_drawdown: null,
    annualized_volatility: null,
    total_fees: null,
    executed_order_count: null,
    equity_curve: [],
    drawdown_curve: [],
    trades: [],
  }
}

function bearishTrendResponse() {
  return {
    ...meanReversionResponse(),
    symbol: 'XOM',
    market_regime: 'bearish_trend',
    selected_strategy: 'trend_following',
    evaluation_strategy: 'trend_following',
    strategy_mode: 'active',
    allow_new_long: false,
    risk_off: false,
    strategy_parameters: { strategy: 'Core-Only Medium-Term Trend Following' },
  }
}

test('maps the three formal strategy keys to user-facing labels', () => {
  assert.equal(formatStrategyLabel('trend_following'), 'Trend Following')
  assert.equal(formatStrategyLabel('mean_reversion'), 'Mean Reversion')
  assert.equal(formatStrategyLabel('risk_off'), 'Risk Off')
  assert.equal(formatStrategyLabel(null), 'N/A')
})

test('maps strategy mode and execution mode labels', () => {
  assert.equal(formatStrategyModeLabel('active'), 'Active')
  assert.equal(formatStrategyModeLabel('defensive'), 'Defensive')
  assert.equal(formatExecutionModeLabel('long_only'), 'Long Only')
  assert.equal(formatStrategyModeLabel(null), 'N/A')
  assert.equal(formatExecutionModeLabel(null), 'N/A')
})

test('Allow New Long only renders Yes or No for real booleans', () => {
  assert.equal(formatAllowNewLong(true), 'Yes')
  assert.equal(formatAllowNewLong(false), 'No')
  assert.equal(formatAllowNewLong(null), 'N/A')
  assert.equal(formatAllowNewLong(undefined), 'N/A')
})

test('backend percentage-point values are displayed without multiplying by 100', () => {
  assert.equal(formatEvaluationPercent(12.3456), '12.35%')
  assert.equal(formatEvaluationPercent(12.3456, { signed: true }), '+12.35%')
  assert.equal(formatEvaluationPercent(-3.14, { signed: true }), '-3.14%')
  assert.equal(formatEvaluationPercent(0), '0.00%')
  assert.equal(formatEvaluationPercent(null), 'N/A')
})

test('missing money and trade-count values render N/A instead of zero', () => {
  assert.equal(formatEvaluationMoney('10000.000000'), '$10,000.00')
  assert.equal(formatEvaluationMoney(null), 'N/A')
  assert.equal(formatEvaluationMoney(undefined), 'N/A')
  assert.equal(formatTradeCount(3), '3')
  assert.equal(formatTradeCount(0), '0')
  assert.equal(formatTradeCount(null), 'N/A')
})

test('normalizes a completed Mean Reversion evaluation with backend values', () => {
  const view = normalizeStrategyEvaluation(meanReversionResponse(), 'JPM')

  assert.equal(view.symbol, 'JPM')
  assert.equal(view.selectionAvailable, true)
  assert.equal(view.marketRegime, 'sideways_range')
  assert.equal(view.selectedStrategy, 'mean_reversion')
  assert.equal(view.strategyLabel, 'Mean Reversion')
  assert.equal(view.strategyModeLabel, 'Active')
  assert.equal(view.executionModeLabel, 'Long Only')
  assert.equal(view.allowNewLong, true)
  assert.equal(view.riskOff, false)
  assert.equal(view.selectionConfidence, 'High')
  assert.equal(view.evaluationAvailable, true)
  assert.equal(view.evaluationStatus, 'completed')
  assert.equal(view.metrics.totalReturn, 12.345678)
  assert.equal(view.metrics.finalEquity, 10123.45)
  assert.equal(view.metrics.executedOrderCount, 3)
  assert.deepEqual(view.reason, [
    'The current market regime is Sideways / Range.',
    'Mean Reversion is preferred under the current regime.',
  ])
  assert.deepEqual(view.evaluationWindow, {
    start_date: '2025-08-14',
    end_date: '2026-08-13',
  })
  assert.equal(view.dataSource.source, 'database_cache')
  assert.equal(view.equityCurve.length, 1)
})

test('Risk-Off normalizes to defensive state without converting nulls to zero', () => {
  const view = normalizeStrategyEvaluation(riskOffResponse(), 'AAPL')

  assert.equal(view.selectedStrategy, 'risk_off')
  assert.equal(view.strategyLabel, 'Risk Off')
  assert.equal(view.strategyModeLabel, 'Defensive')
  assert.equal(view.executionModeLabel, 'Long Only')
  assert.equal(view.allowNewLong, false)
  assert.equal(view.riskOff, true)
  assert.equal(view.evaluationAvailable, false)
  assert.equal(view.evaluationStatus, 'not_applicable')
  assert.equal(view.metrics.initialCapital, null)
  assert.equal(view.metrics.finalEquity, null)
  assert.equal(view.metrics.totalReturn, null)
  assert.equal(view.metrics.maximumDrawdown, null)
  assert.equal(view.metrics.annualizedVolatility, null)
  assert.equal(view.metrics.totalFees, null)
  assert.equal(view.metrics.executedOrderCount, null)
  assert.equal(view.equityCurve.length, 0)
  assert.equal(view.trades.length, 0)
})

test('Bearish Trend keeps Trend Following and still exposes the historical evaluation', () => {
  const view = normalizeStrategyEvaluation(bearishTrendResponse(), 'XOM')

  assert.equal(view.marketRegime, 'bearish_trend')
  assert.equal(view.selectedStrategy, 'trend_following')
  assert.equal(view.strategyLabel, 'Trend Following')
  assert.equal(view.allowNewLong, false)
  assert.equal(view.riskOff, false)
  assert.equal(view.evaluationAvailable, true)
  assert.equal(view.evaluationStatus, 'completed')
  assert.equal(view.evaluationStrategy, 'trend_following')
  assert.equal(view.metrics.totalReturn, 12.345678)
})

test('switching symbols immediately hides the previous evaluation behind loading state', () => {
  const aapl = normalizeStrategyEvaluation(riskOffResponse(), 'AAPL')
  const requestState = { symbol: 'AAPL', status: 'ready', data: aapl, error: '' }
  const panel = getStrategyEvaluationPanelState(requestState, 'JPM')

  assert.equal(panel.symbol, 'JPM')
  assert.equal(panel.status, 'loading')
  assert.equal(panel.data, null)
  assert.equal(panel.error, '')
})

test('only the latest strategy-evaluation request may publish results', () => {
  assert.equal(isCurrentStrategyEvaluationRequest(3, 1), false)
  assert.equal(isCurrentStrategyEvaluationRequest(3, 2), false)
  assert.equal(isCurrentStrategyEvaluationRequest(3, 3), true)
})

test('identity checks reject a response for a different symbol', () => {
  assert.equal(strategyEvaluationResponseMatchesSymbol(meanReversionResponse(), 'JPM'), true)
  assert.equal(strategyEvaluationResponseMatchesSymbol(meanReversionResponse(), 'XOM'), false)
  assert.throws(() => normalizeStrategyEvaluation(meanReversionResponse(), 'XOM'), /did not match/)
})

test('unavailable reason codes and human sentences stay readable', () => {
  assert.equal(
    formatUnavailableReason('Risk-Off is a defensive state rather than an active trading strategy.'),
    'Risk-Off is a defensive state rather than an active trading strategy.',
  )
  assert.equal(
    formatUnavailableReason('strategy_selection_unavailable'),
    'Strategy selection unavailable.',
  )
  assert.equal(
    formatUnavailableReason(null),
    'Historical evaluation is unavailable for the selected strategy.',
  )
})
