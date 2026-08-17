import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

let vite
let StrategyEvaluationPanel
let normalizeStrategyEvaluation

before(async () => {
  vite = await createServer({ appType: 'custom', server: { hmr: false, middlewareMode: true } })
  ;({ default: StrategyEvaluationPanel } = await vite.ssrLoadModule(
    '/src/components/market-analysis/StrategyEvaluationPanel.jsx',
  ))
  ;({ normalizeStrategyEvaluation } = await vite.ssrLoadModule(
    '/src/components/market-analysis/strategyEvaluationModel.js',
  ))
})

after(async () => {
  await vite?.close()
})

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

function trendResponse({ bearish = false } = {}) {
  return {
    ...meanReversionResponse(),
    symbol: bearish ? 'XOM' : 'MSFT',
    market_regime: bearish ? 'bearish_trend' : 'bullish_trend',
    selected_strategy: 'trend_following',
    evaluation_strategy: 'trend_following',
    allow_new_long: !bearish,
    risk_off: false,
    strategy_parameters: { strategy: 'Core-Only Medium-Term Trend Following' },
    reason: [
      bearish
        ? 'The current market regime is Bearish Trend.'
        : 'The current market regime is Bullish Trend.',
      'Trend Following remains the selected strategy for a directional market.',
    ],
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
    selection_confidence: 'medium',
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

function renderPanel(props) {
  const html = renderToStaticMarkup(React.createElement(StrategyEvaluationPanel, props))
  return {
    html,
    text: html.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim(),
  }
}

test('Mean Reversion evaluation renders selection, confidence and real metrics', () => {
  const evaluation = normalizeStrategyEvaluation(meanReversionResponse(), 'JPM')
  const { text } = renderPanel({
    symbol: 'JPM',
    evaluation,
    isLoading: false,
    error: '',
  })

  assert.match(text, /Strategy Evaluation JPM Mean Reversion Confidence: High/)
  assert.match(text, /Strategy Selection Selected Strategy Mean Reversion/)
  assert.match(text, /Strategy Mode Active/)
  assert.match(text, /Execution Mode Long Only/)
  assert.match(text, /Allow New Long Yes/)
  assert.match(text, /Selection Confidence High/)
  assert.match(text, /Historical Strategy Evaluation Total Return \+12\.35%/)
  assert.match(text, /Final Equity \$10,123\.45/)
  assert.match(text, /Maximum Drawdown 8\.12%/)
  assert.match(text, /Annualized Volatility 15\.25%/)
  assert.match(text, /Executed Orders 3/)
  assert.match(text, /Total Fees \$2\.00/)
  assert.match(text, /Why this strategy\?/)
  assert.match(text, /The current market regime is Sideways \/ Range\./)
  assert.match(text, /Evaluation window: 2025-08-14 to 2026-08-13/)
  assert.match(text, /Data source: Cached market data/)
})

test('Bullish Trend renders Trend Following with Allow New Long Yes and evaluation', () => {
  const evaluation = normalizeStrategyEvaluation(trendResponse(), 'MSFT')
  const { text } = renderPanel({
    symbol: 'MSFT',
    evaluation,
    isLoading: false,
    error: '',
  })

  assert.match(text, /Selected Strategy Trend Following/)
  assert.match(text, /Allow New Long Yes/)
  assert.match(text, /Historical Strategy Evaluation Total Return \+12\.35%/)
  assert.doesNotMatch(text, /Risk Off/)
})

test('Bearish Trend keeps Trend Following and Allow New Long No while evaluation remains', () => {
  const evaluation = normalizeStrategyEvaluation(trendResponse({ bearish: true }), 'XOM')
  const { text } = renderPanel({
    symbol: 'XOM',
    evaluation,
    isLoading: false,
    error: '',
  })

  assert.match(text, /Selected Strategy Trend Following/)
  assert.match(text, /Allow New Long No/)
  assert.match(text, /Historical Strategy Evaluation Total Return \+12\.35%/)
  assert.doesNotMatch(text, /Selected Strategy Risk Off|Strategy Mode Defensive/)
})

test('Risk-Off renders Not Applicable with the reason and never formats null as zero', () => {
  const evaluation = normalizeStrategyEvaluation(riskOffResponse(), 'AAPL')
  const { html, text } = renderPanel({
    symbol: 'AAPL',
    evaluation,
    isLoading: false,
    error: '',
  })

  assert.match(text, /Selected Strategy Risk Off/)
  assert.match(text, /Strategy Mode Defensive/)
  assert.match(text, /Execution Mode Long Only/)
  assert.match(text, /Allow New Long No/)
  assert.match(text, /Confidence: Medium/)
  assert.match(text, /Historical Strategy Evaluation Not Applicable/)
  assert.match(text, /Risk-Off is a defensive state rather than an active trading strategy\./)
  assert.doesNotMatch(text, /0\.00%|\$0\.00|0 trades|Return 0/)
  assert.doesNotMatch(html, /role="alert"/)
})

test('business-unavailable selection renders a calm message instead of an API error', () => {
  const raw = {
    ...riskOffResponse(),
    strategy_selection_available: false,
    market_regime: null,
    selected_strategy: null,
    strategy_mode: null,
    allow_new_long: null,
    risk_off: null,
    selection_confidence: null,
    evaluation_status: 'unavailable',
    evaluation_unavailable_reason: 'market_regime_unavailable',
    reason: ['Strategy selection is unavailable because the market regime is unavailable.'],
  }
  const evaluation = normalizeStrategyEvaluation(raw, 'AAPL')
  const { html, text } = renderPanel({
    symbol: 'AAPL',
    evaluation,
    isLoading: false,
    error: '',
  })

  assert.match(text, /Strategy selection unavailable for AAPL/)
  assert.match(text, /Strategy selection is unavailable because the market regime is unavailable\./)
  assert.doesNotMatch(html, /role="alert"/)
  assert.doesNotMatch(text, /temporarily unavailable|Retry/)
})

test('HTTP error renders an isolated alert state with Retry', () => {
  const { html, text } = renderPanel({
    symbol: 'AAPL',
    evaluation: null,
    isLoading: false,
    error: 'Unable to load strategy evaluation for AAPL.',
    onRetry: () => {},
  })

  assert.match(html, /role="alert"/)
  assert.match(text, /Strategy evaluation temporarily unavailable/)
  assert.match(text, /Unable to load strategy evaluation for AAPL\./)
  assert.match(text, /Retry/)
  assert.doesNotMatch(text, /NaN|undefined|0\.00%/)
})

test('loading a new symbol never renders the previous stock evaluation', () => {
  const oldEvaluation = normalizeStrategyEvaluation(riskOffResponse(), 'AAPL')
  const { text } = renderPanel({
    symbol: 'JPM',
    evaluation: oldEvaluation,
    isLoading: true,
    error: '',
  })

  assert.match(text, /Loading strategy evaluation for JPM/)
  assert.doesNotMatch(text, /AAPL|Risk Off|Defensive|Not Applicable|High Volatility/)
})
