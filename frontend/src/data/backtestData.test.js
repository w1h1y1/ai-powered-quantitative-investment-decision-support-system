import assert from 'node:assert/strict'
import test from 'node:test'

import {
  backtestBenchmarkOptions,
  backtestMarketBenchmark,
  buildBacktestFailureState,
  buildBacktestRequestPayload,
  createDefaultBacktestConfig,
  createBacktestRunRequest,
  defaultBacktestConfig,
  filterBacktestBenchmarkOptions,
  normalizeBacktestResult,
  sanitizeBacktestBenchmarkSymbol,
  sanitizeBacktestHistory,
  validateBacktestConfig,
} from './backtestData.js'

function buildResponse() {
  return {
    id: 'backtest-hybrid-test',
    run_at: '2026-08-05T10:00:00Z',
    initial_capital: '10000.000000',
    final_equity: '10400.000000',
    total_return: '4.000000',
    maximum_drawdown: '2.500000',
    annualized_volatility: '11.000000',
    total_fees: '3.000000',
    executed_order_count: 3,
    core_return_contribution: '3.000000',
    core_realized_profit_loss: '100.000000',
    core_unrealized_profit_loss: '200.000000',
    core_holding_days: 40,
    core_entry_count: 1,
    core_exit_count: 0,
    core_add_count: 2,
    core_reduce_count: 1,
    core_full_exit_count: 0,
    average_core_holding_period: '40.000000',
    median_core_holding_period: '40.000000',
    average_core_exposure: '32.500000',
    max_core_exposure: '55.000000',
    full_exit_to_next_buy_average_gap: '0.000000',
    full_exit_to_next_buy_minimum_gap: 0,
    core_strategy_diagnostics: {
      core_buy_count: 1,
      core_add_count: 2,
      core_reduce_count: 1,
      core_full_exit_count: 0,
      trend_state_counts: { STRONG_BULL: 10, BULL: 20, WEAK_BULL: 8, BEAR: 3, REVERSAL_SETUP: 1 },
      reentry_reasons: { CORE_ENTRY_BULL: 1 },
      reduce_reasons: { CORE_REDUCE_WEAK_TREND: 1 },
      full_exit_reasons: {},
    },
    swing_return_contribution: '1.000000',
    swing_realized_profit_loss: '100.000000',
    swing_unrealized_profit_loss: '0.000000',
    swing_cycle_count: 1,
    swing_entry_count: 1,
    swing_exit_count: 1,
    average_days_per_swing_cycle: '4.000000',
    median_days_per_swing_cycle: '3.000000',
    minimum_days_per_swing_cycle: 1,
    maximum_days_per_swing_cycle: 7,
    profitable_swing_cycle_count: 1,
    swing_win_rate: '100.000000',
    average_swing_return: '2.000000',
    swing_fees: '2.000000',
    swing_total_fees: '2.000000',
    swing_turnover: '30.000000',
    swing_holding_period_diagnostics: {
      swing_round_trip_count: 1,
      holding_1_bar_count: 1,
      holding_2_bars_count: 0,
      holding_3_to_5_bars_count: 0,
      holding_over_5_bars_count: 0,
      round_trips: [],
    },
    swing_signal_diagnostics: {
      eligible_core_days: 42,
      market_bear_days: 3,
      rsi_pullback_detected_days: 12,
      rsi_upward_cross_days: 2,
      close_above_trend_average_days: 38,
      swing_entry_signal_count: 1,
      swing_exit_signal_count: 1,
      primary_block_reason_counts: { NO_RSI_PULLBACK: 20, ENTRY_SIGNAL_CREATED: 1 },
    },
    equity_curve: [{
      date: '2026-01-02',
      close: '120.000000',
      cash: '7000.000000',
      holdings_value: '3400.000000',
      total_equity: '10400.000000',
      ma10: '117.000000',
      ema10: '118.000000',
      swing_average: '118.000000',
      swing_average_type: 'EMA10',
      ma20: '115.000000',
      ma60: '110.000000',
      rsi14: '52.000000',
      atr14: '2.000000',
      macd: '1.500000',
      macd_signal: '1.250000',
      macd_histogram: '0.250000',
      bollinger_upper: '125.000000',
      market_regime: 'BULL',
      trend_state: 'STRONG_BULL',
      trend_bear_score: 0,
      trend_reversal_score: 1,
      core_quantity: '25.00000000',
      core_average_cost: '100.040000',
      swing_quantity: '0.00000000',
      swing_average_cost: '0.000000',
      core_exposure: '28.846154',
      swing_exposure: '0.000000',
      total_exposure: '28.846154',
      drawdown: '0.000000',
    }],
    drawdown_curve: [{ date: '2026-01-02', drawdown: '0.000000' }],
    trades: [{
      id: 'trade-1',
      position_layer: 'CORE',
      reason: 'CORE_ENTRY_BULL',
      signal_date: '2026-01-01',
      execution_date: '2026-01-02',
      type: 'BUY',
      execution_price: '100.000000',
      quantity: '25.00000000',
      fee: '1.000000',
      cash_after: '7499.000000',
      core_quantity_after: '25.00000000',
      swing_quantity_after: '0.00000000',
      total_quantity_after: '25.00000000',
      realized_profit_loss: '0.000000',
      equity_before: '10000.000000',
      risk_fraction: '0.020000',
      risk_amount: '200.000000',
      atr: '2.000000',
      stop_distance: '5.000000',
      raw_quantity: '40.00000000',
      affordable_quantity: '99.99000000',
      exposure_capped_quantity: '80.00000000',
      final_quantity: '40.00000000',
      raw_exposure: '40.000000',
      final_exposure: '40.000000',
      exposure_cap_applied: false,
      cash_cap_applied: false,
    }],
    comparisons: [
      { strategy: 'Buy and Hold', strategy_id: 'buy-and-hold', total_return: '5', final_equity: '10500', maximum_drawdown: '3', annualized_volatility: '12', total_fees: '1', executed_orders: 1 },
      { strategy: 'Core-Only Medium-Term Strategy', strategy_id: 'core-only', total_return: '3', final_equity: '10300', maximum_drawdown: '2', annualized_volatility: '9', total_fees: '1', executed_orders: 1 },
      { strategy: 'Core + Swing Hybrid Strategy', strategy_id: 'core-swing-hybrid', total_return: '4', final_equity: '10400', maximum_drawdown: '2.5', annualized_volatility: '11', total_fees: '3', executed_orders: 3 },
    ],
    strategy_parameters: {
      strategy_id: 'market-regime-core-swing',
      benchmark: 'SPY',
      transaction_fee: '1.000000',
      core_fast_ma: 20,
      core_slow_ma: 60,
      core_risk_fraction: '0.020000',
      core_risk_percentage: '0.020000',
      core_atr_multiplier: '2.500000',
      max_core_exposure: '0.800000',
      core_reduce_fraction: '0.250000',
      swing_risk_fraction: '0.010000',
      swing_risk_percentage: '0.010000',
      swing_atr_multiplier: '1.500000',
      swing_rsi_lookback: 10,
      swing_rsi_entry_level: '45.000000',
      swing_rsi_exit_level: '60.000000',
      swing_trend_average: 'EMA10',
      swing_average_type: 'EMA10',
    },
    security: { id: 1, symbol: 'TEST', name: 'Test Security', asset_type: 'STOCK', exchange: 'NASDAQ', currency: 'USD' },
    benchmark: { id: 2, symbol: 'SPY', name: 'SPDR S&P 500 ETF' },
    data_source: { requested_start_date: '2026-01-01', requested_end_date: '2026-01-31', source: 'database_cache' },
  }
}

test('default Market-Regime Core and Swing configuration validates', () => {
  assert.deepEqual(validateBacktestConfig(defaultBacktestConfig), {})
  assert.equal(defaultBacktestConfig.benchmarkSymbol, 'SPY')
  assert.equal(defaultBacktestConfig.coreRiskPercent, '2')
  assert.equal(defaultBacktestConfig.coreAtrMultiplier, '2.5')
  assert.equal(defaultBacktestConfig.maxCoreExposurePercent, '80')
  assert.equal(defaultBacktestConfig.coreReduceFractionPercent, '25')
  assert.equal(defaultBacktestConfig.swingRiskPercent, '1')
  assert.equal(defaultBacktestConfig.swingAtrMultiplier, '1.5')
  assert.equal(defaultBacktestConfig.swingRsiLookback, '10')
  assert.equal(defaultBacktestConfig.swingRsiEntryLevel, '45')
  assert.equal(defaultBacktestConfig.swingRsiExitLevel, '60')
  assert.equal(defaultBacktestConfig.swingAverageType, 'EMA10')
  assert.equal('swingCooldownDays' in defaultBacktestConfig, false)
})

test('Backtest market benchmark defaults to SPY broad-market reference', () => {
  assert.equal(backtestMarketBenchmark.symbol, 'SPY')
  assert.equal(backtestMarketBenchmark.name, 'SPDR S&P 500 ETF')
  assert.equal(defaultBacktestConfig.benchmarkSymbol, 'SPY')
})

test('Backtest benchmark whitelist contains benchmark ETFs only', () => {
  const symbols = backtestBenchmarkOptions.map((option) => option.symbol)
  for (const symbol of ['SPY', 'QQQ', 'XLF', 'XLE', 'XLC']) {
    assert.ok(symbols.includes(symbol), `expected ${symbol} in whitelist`)
  }
  for (const symbol of ['AAPL', 'MSFT', 'TSLA', 'JPM']) {
    assert.ok(!symbols.includes(symbol), `${symbol} must not be a benchmark option`)
  }
})

test('benchmark sanitization keeps whitelist symbols and falls back to SPY otherwise', () => {
  assert.equal(sanitizeBacktestBenchmarkSymbol('qqq'), 'QQQ')
  assert.equal(sanitizeBacktestBenchmarkSymbol('QQQ', ['SPY', 'QQQ', 'XLF']), 'QQQ')
  assert.equal(sanitizeBacktestBenchmarkSymbol('AAPL'), 'SPY')
  assert.equal(sanitizeBacktestBenchmarkSymbol('QQQ', ['SPY', 'XLF']), 'SPY')
  assert.equal(sanitizeBacktestBenchmarkSymbol(null), 'SPY')
})

test('benchmark options are filtered by asset-allowed symbols and existing assets', () => {
  const assets = [
    { symbol: 'SPY' },
    { symbol: 'QQQ' },
    { symbol: 'XLK' },
    { symbol: 'XOM' },
  ]

  const aaplOptions = filterBacktestBenchmarkOptions(['SPY', 'XLK', 'QQQ'], assets)
  assert.deepEqual(aaplOptions.map((option) => option.symbol), ['SPY', 'QQQ', 'XLK'])
  assert.ok(!aaplOptions.some((option) => option.symbol === 'XLF'))

  const xomOptions = filterBacktestBenchmarkOptions(['SPY', 'XLE'], assets)
  assert.deepEqual(xomOptions.map((option) => option.symbol), ['SPY'])
})

test('Backtest request payload propagates the selected benchmark', () => {
  const config = createDefaultBacktestConfig()
  const asset = { symbol: 'AAPL', name: 'Apple Inc.', exchange: 'NASDAQ', type: 'Stock' }

  const payload = buildBacktestRequestPayload(config, asset)

  assert.equal(payload.benchmark, 'SPY')
  assert.equal(payload.security_selection.symbol, 'AAPL')

  const qqqConfig = { ...createDefaultBacktestConfig(), benchmarkSymbol: 'QQQ' }
  const qqqPayload = buildBacktestRequestPayload(qqqConfig, asset)
  assert.equal(qqqPayload.benchmark, 'QQQ')

  const xlkConfig = { ...createDefaultBacktestConfig(), benchmarkSymbol: 'XLK' }
  const xlkPayload = buildBacktestRequestPayload(xlkConfig, asset)
  assert.equal(xlkPayload.benchmark, 'XLK')
})

test('normalized result config records the selected benchmark and rejects non-whitelist values', () => {
  const response = buildResponse()
  response.benchmark = { id: 4, symbol: 'QQQ', name: 'Invesco QQQ ETF' }
  const fallbackConfig = { benchmarkSymbol: 'SPY' }

  const result = normalizeBacktestResult(response, fallbackConfig)

  assert.equal(result.config.benchmarkSymbol, 'QQQ')
  assert.equal(result.asset.symbol, 'TEST')

  response.benchmark = { id: 99, symbol: 'AAPL', name: 'Apple Inc.' }
  const sanitized = normalizeBacktestResult(response, fallbackConfig)
  assert.equal(sanitized.config.benchmarkSymbol, 'SPY')
})

test('Backtest date defaults use the local calendar date and one calendar year lookback', () => {
  const config = createDefaultBacktestConfig(new Date(2026, 7, 9, 0, 15))

  assert.equal(config.endDate, '2026-08-09')
  assert.equal(config.startDate, '2025-08-09')
  assert.match(config.startDate, /^\d{4}-\d{2}-\d{2}$/)
  assert.match(config.endDate, /^\d{4}-\d{2}-\d{2}$/)
})

test('Backtest one-year lookback clamps leap day without UTC conversion', () => {
  const config = createDefaultBacktestConfig(new Date(2024, 1, 29, 0, 15))

  assert.equal(config.endDate, '2024-02-29')
  assert.equal(config.startDate, '2023-02-28')
})

test('normalizeBacktestResult preserves layered positions, indicators, trades, and comparisons', () => {
  const result = normalizeBacktestResult(buildResponse())

  assert.equal(result.schemaVersion, 6)
  assert.equal(result.strategy.id, 'market-regime-core-swing')
  assert.equal(result.benchmark.symbol, 'SPY')
  assert.deepEqual(
    [result.points[0].ma10, result.points[0].ma20, result.points[0].ma60, result.points[0].marketRegime],
    [117, 115, 110, 'BULL'],
  )
  assert.deepEqual(
    [result.points[0].macd, result.points[0].macdSignal, result.points[0].macdHistogram, result.points[0].trendState],
    [1.5, 1.25, 0.25, 'STRONG_BULL'],
  )
  assert.equal(result.points[0].coreQuantity, 25)
  assert.equal(result.points[0].swingQuantity, 0)
  assert.equal(result.trades[0].positionLayer, 'CORE')
  assert.equal(result.trades[0].reason, 'CORE_ENTRY_BULL')
  assert.equal(result.trades[0].coreQuantityAfter, 25)
  assert.equal(result.trades[0].riskFraction, 0.02)
  assert.equal(result.metrics.executedOrderCount, 3)
  assert.equal(result.coreMetrics.holdingDays, 40)
  assert.equal(result.coreMetrics.addCount, 2)
  assert.equal(result.coreMetrics.reduceCount, 1)
  assert.equal(result.coreMetrics.averageExposure, 32.5)
  assert.equal(result.swingMetrics.cycleCount, 1)
  assert.equal(result.comparisons.length, 3)
  assert.equal(result.config.coreRiskPercent, '2')
  assert.equal(result.config.maxCoreExposurePercent, '80')
  assert.equal(result.config.coreReduceFractionPercent, '25')
  assert.equal(result.config.coreAtrMultiplier, '2.5')
  assert.equal(result.parametersUsed.swingRiskPercent, 1)
  assert.equal(result.parametersUsed.swingRsiLookback, 10)
  assert.equal('swingCooldownDays' in result.parametersUsed, false)
  assert.equal(result.points[0].swingAverage, 118)
  assert.equal(result.swingMetrics.averageDaysPerCycle, 4)
  assert.equal(result.swingMetrics.medianDaysPerCycle, 3)
  assert.equal(result.swingMetrics.oneBarCycleCount, 1)
  assert.equal(result.swingMetrics.losingCycleCount, 0)
  assert.equal(result.swingHoldingPeriodDiagnostics.swing_round_trip_count, 1)
  assert.equal(result.swingSignalDiagnostics.eligible_core_days, 42)
  assert.equal(result.swingSignalDiagnostics.swing_entry_signal_count, 1)
  assert.equal(result.swingSignalDiagnostics.primary_block_reason_counts.NO_RSI_PULLBACK, 20)
  assert.equal(result.coreStrategyDiagnostics.trend_state_counts.STRONG_BULL, 10)
})

test('normalization preserves missing indicator values as null instead of zero', () => {
  const response = buildResponse()
  response.equity_curve[0].ma10 = null
  response.equity_curve[0].ma20 = null
  response.equity_curve[0].ma60 = null

  const result = normalizeBacktestResult(response)

  assert.equal(result.points[0].ma10, null)
  assert.equal(result.points[0].ma20, null)
  assert.equal(result.points[0].ma60, null)
})

test('old Moving Average Crossover history is not reused as hybrid strategy output', () => {
  const oldResult = {
    ...normalizeBacktestResult(buildResponse()),
    schemaVersion: 2,
  }

  assert.deepEqual(sanitizeBacktestHistory([oldResult]), [])
})

test('invalid risk fractions and Core MA ordering are rejected before API submission', () => {
  const errors = validateBacktestConfig({
    ...defaultBacktestConfig,
    coreFastMa: '60',
    coreSlowMa: '20',
    coreRiskPercent: '0',
    swingRiskPercent: '20',
  })

  assert.ok(errors.coreFastMa)
  assert.ok(errors.coreRiskPercent)
  assert.ok(errors.swingRiskPercent)
})

test('risk fraction limits reject values that look like accidental large percentages', () => {
  const errors = validateBacktestConfig({
    ...defaultBacktestConfig,
    coreRiskPercent: '5.1',
    swingRiskPercent: '2.1',
  })

  assert.match(errors.coreRiskPercent, /0.1% and 5%/)
  assert.match(errors.swingRiskPercent, /0.1% and 2%/)
})

test('request payload uses the latest config and serializes every numeric parameter as a number', () => {
  const config = {
    ...defaultBacktestConfig,
    coreFastMa: '5',
    coreSlowMa: '10',
    coreRiskPercent: '2',
    coreAtrMultiplier: '4.000000',
    maxCoreExposurePercent: '20',
    coreReduceFractionPercent: '30',
    swingRiskPercent: '1',
    swingAtrMultiplier: '2.500000',
    swingRsiLookback: '8',
    swingRsiEntryLevel: '50',
    swingRsiExitLevel: '58',
    swingAverageType: 'EMA10',
  }

  const payload = buildBacktestRequestPayload(config, 42)

  assert.deepEqual(
    {
      security: payload.security,
      core_fast_ma: payload.core_fast_ma,
      core_slow_ma: payload.core_slow_ma,
      core_risk_fraction: payload.core_risk_fraction,
      core_atr_multiplier: payload.core_atr_multiplier,
      max_core_exposure: payload.max_core_exposure,
      core_reduce_fraction: payload.core_reduce_fraction,
      swing_risk_fraction: payload.swing_risk_fraction,
      swing_atr_multiplier: payload.swing_atr_multiplier,
      swing_rsi_lookback: payload.swing_rsi_lookback,
      swing_rsi_entry_level: payload.swing_rsi_entry_level,
      swing_rsi_exit_level: payload.swing_rsi_exit_level,
      swing_trend_average: payload.swing_trend_average,
    },
    {
      security: 42,
      core_fast_ma: 5,
      core_slow_ma: 10,
      core_risk_fraction: 0.02,
      core_atr_multiplier: 4,
      max_core_exposure: 0.2,
      core_reduce_fraction: 0.3,
      swing_risk_fraction: 0.01,
      swing_atr_multiplier: 2.5,
      swing_rsi_lookback: 8,
      swing_rsi_entry_level: 50,
      swing_rsi_exit_level: 58,
      swing_trend_average: 'EMA10',
    },
  )
  Object.values(payload).forEach((value) => {
    if (typeof value === 'number') assert.ok(Number.isFinite(value))
  })
})

test('run request snapshots current asset and parameters without reading an old result', () => {
  const request = createBacktestRunRequest({
    ...defaultBacktestConfig,
    symbol: 'MSFT',
    startDate: '2025-07-01',
    endDate: '2026-06-30',
    coreFastMa: '9',
    coreRiskPercent: '1.5',
    swingRsiEntryLevel: '50',
  }, { id: 77, symbol: 'MSFT', name: 'Microsoft' })

  assert.equal(request.asset.symbol, 'MSFT')
  assert.equal(request.payload.security, 77)
  assert.equal(request.payload.core_fast_ma, 9)
  assert.equal(request.payload.core_risk_fraction, 0.015)
  assert.equal(request.payload.swing_rsi_entry_level, 50)
  assert.equal(request.payload.start_date, '2025-07-01')
  assert.equal(request.payload.end_date, '2026-06-30')
})

test('remote security request carries verified search metadata without inventing a local id', () => {
  const request = createBacktestRunRequest(
    { ...defaultBacktestConfig, symbol: 'TSLA' },
    {
      id: null,
      symbol: 'TSLA',
      name: 'Tesla Inc.',
      type: 'Stock',
      exchange: 'NASDAQ',
      mic_code: 'XNAS',
      instrument_type: 'Common Stock',
      country: 'United States',
      currency: 'USD',
      source: 'remote',
      search_query: 'Tesla',
    },
  )

  assert.equal('security' in request.payload, false)
  assert.equal(request.payload.symbol, 'TSLA')
  assert.deepEqual(request.payload.security_selection, {
    id: null,
    symbol: 'TSLA',
    name: 'Tesla Inc.',
    exchange: 'NASDAQ',
    mic_code: 'XNAS',
    instrument_type: 'Common Stock',
    country: 'United States',
    currency: 'USD',
    search_query: 'Tesla',
  })
})

test('failed request state clears the prior result and identifies the failed asset', () => {
  const request = createBacktestRunRequest(
    { ...defaultBacktestConfig, symbol: 'NVDA' },
    { id: 88, symbol: 'NVDA', name: 'NVIDIA' },
  )
  const failure = buildBacktestFailureState(request, {
    message: 'Not enough warm-up history.',
    data: { required_warmup_rows: 220 },
  })

  assert.equal(failure.currentResult, null)
  assert.equal(failure.error.assetSymbol, 'NVDA')
  assert.equal(failure.error.request.payload.security, 88)
  assert.equal(failure.error.details.required_warmup_rows, 220)
})

test('normalized six-decimal API parameters can be submitted again without precision strings', () => {
  const normalized = normalizeBacktestResult(buildResponse())
  const payload = buildBacktestRequestPayload(normalized.config, normalized.asset.id)

  assert.equal(payload.core_atr_multiplier, 2.5)
  assert.equal(payload.swing_atr_multiplier, 1.5)
  assert.equal('swing_cooldown_days' in payload, false)
  assert.equal(typeof payload.core_atr_multiplier, 'number')
  assert.equal(typeof payload.swing_atr_multiplier, 'number')
})

test('schema 3 fraction-based saved results migrate to percentage inputs without being discarded', () => {
  const current = normalizeBacktestResult(buildResponse())
  const legacy = {
    ...current,
    schemaVersion: 3,
    config: {
      ...current.config,
      coreRiskPercentage: '0.010000',
      coreAtrMultiplier: '2.000000',
      maxCoreExposure: '0.700000',
      swingRiskPercentage: '0.005000',
      swingAtrMultiplier: '1.500000',
    },
  }
  delete legacy.config.coreRiskPercent
  delete legacy.config.maxCoreExposurePercent
  delete legacy.config.swingRiskPercent

  const [migrated] = sanitizeBacktestHistory([legacy])

  assert.equal(migrated.schemaVersion, 6)
  assert.equal(migrated.config.coreRiskPercent, '1')
  assert.equal(migrated.config.maxCoreExposurePercent, '70')
  assert.equal(migrated.config.swingRiskPercent, '0.5')
  assert.equal(migrated.config.coreAtrMultiplier, '2.0')
  assert.equal(migrated.config.swingAtrMultiplier, '1.5')
  assert.equal(migrated.config.swingRsiLookback, '5')
  assert.equal(migrated.config.swingRsiEntryLevel, '40')
  assert.equal(migrated.config.swingRsiExitLevel, '65')
  assert.equal(migrated.config.swingAverageType, 'SMA10')
  assert.equal('swingCooldownDays' in migrated.config, false)
  assert.equal('swingCooldownDays' in migrated.parametersUsed, false)
})
