import {
  formatCurrency,
  formatPercentage,
  formatSignedPercentage,
} from '../portfolio/portfolioMath'
import BacktestExposureChart from './BacktestExposureChart'
import BacktestLineChart from './BacktestLineChart'
import BacktestPriceSignalChart from './BacktestPriceSignalChart'
import TradeHistoryTable from './TradeHistoryTable'

function getTone(value, positiveThreshold = 0) {
  if (value > positiveThreshold) return 'is-positive'
  if (value < 0) return 'is-negative'
  return 'is-neutral'
}

function LayerMetric({ label, value, tone = '' }) {
  return (
    <div className="backtest-layer-metric">
      <span>{label}</span>
      <strong className={tone}>{value}</strong>
    </div>
  )
}

function formatCompactNumber(value, minimumFractionDigits = 0) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 'N/A'
  return parsed.toLocaleString('en-US', {
    maximumFractionDigits: 2,
    minimumFractionDigits,
  })
}

function formatReasonCounts(reasonCounts) {
  const entries = Object.entries(reasonCounts || {})
  if (!entries.length) return 'None'
  return entries.map(([reason, count]) => `${reason} × ${count}`).join(', ')
}

export default function BacktestResults({ result }) {
  const metrics = [
    {
      label: 'Total Return',
      value: formatSignedPercentage(result.metrics.totalReturn),
      detail: 'Hybrid final equity versus initial capital',
      tone: getTone(result.metrics.totalReturn),
    },
    {
      label: 'Final Equity',
      value: formatCurrency(result.metrics.finalEquity),
      detail: 'Cash plus Core and Swing holdings',
      tone: getTone(result.metrics.finalEquity - Number(result.config.initialCapital)),
    },
    {
      label: 'Maximum Drawdown',
      value: formatPercentage(result.metrics.maximumDrawdown),
      detail: 'Largest peak-to-trough decline',
      tone: result.metrics.maximumDrawdown <= 10 ? 'is-neutral' : 'is-negative',
    },
    {
      label: 'Annualized Volatility',
      value: formatPercentage(result.metrics.annualizedVolatility),
      detail: 'Daily equity volatility annualized',
      tone: 'is-neutral',
    },
    {
      label: 'Executed Orders',
      value: String(result.metrics.executedOrderCount),
      detail: 'Core and Swing executions',
      tone: 'is-neutral',
    },
    {
      label: 'Total Fees',
      value: formatCurrency(result.metrics.totalFees),
      detail: 'All executed order fees',
      tone: 'is-neutral',
    },
  ]
  const dataSource = result.dataSource || {}
  const parameters = result.parametersUsed || {}
  const parametersUsed = [
    ['Asset', result.asset?.symbol || 'N/A'],
    ['Benchmark', result.benchmark?.symbol || result.config?.benchmarkSymbol || 'SPY'],
    [
      'Date Range',
      dataSource.requested_start_date && dataSource.requested_end_date
        ? `${dataSource.requested_start_date} to ${dataSource.requested_end_date}`
        : 'N/A',
    ],
    ['Core Fast MA', formatCompactNumber(parameters.coreFastMa)],
    ['Core Slow MA', formatCompactNumber(parameters.coreSlowMa)],
    ['Core Risk', `${formatCompactNumber(parameters.coreRiskPercent)}%`],
    ['Core ATR', formatCompactNumber(parameters.coreAtrMultiplier, 1)],
    ['Max Core Exposure', `${formatCompactNumber(parameters.maxCoreExposurePercent)}%`],
    ['Core Reduce Fraction', `${formatCompactNumber(parameters.coreReduceFractionPercent)}%`],
    ['Swing Risk', `${formatCompactNumber(parameters.swingRiskPercent)}%`],
    ['Swing ATR', formatCompactNumber(parameters.swingAtrMultiplier, 1)],
    ['RSI Lookback', formatCompactNumber(parameters.swingRsiLookback)],
    ['RSI Entry', formatCompactNumber(parameters.swingRsiEntryLevel)],
    ['RSI Exit', formatCompactNumber(parameters.swingRsiExitLevel)],
    ['Swing Average', parameters.swingAverageType || 'EMA10'],
  ]

  return (
    <section className="backtest-results" aria-label={`${result.asset.symbol} ${result.strategy.label} backtest results`}>
      <div className="backtest-metrics-grid" aria-label="Backtest result metrics">
        {metrics.map((metric) => (
          <article className={`backtest-metric-card ${metric.tone}`} key={metric.label}>
            <span>{metric.label}</span>
            <strong>{metric.value}</strong>
            <small>{metric.detail}</small>
          </article>
        ))}
      </div>

      <section className="backtest-card backtest-parameters-used" aria-labelledby="backtest-parameters-used-title">
        <div>
          <p>Executed configuration</p>
          <h2 id="backtest-parameters-used-title">Parameters Used</h2>
        </div>
        <dl>
          {parametersUsed.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </section>

      {result.signalMessage && (
        <p className="backtest-no-signals" role="status">{result.signalMessage}</p>
      )}

      <section className="backtest-card backtest-layer-metrics-card" aria-labelledby="backtest-layer-metrics-title">
        <div className="backtest-card-header">
          <div>
            <p>Independent accounting</p>
            <h2 id="backtest-layer-metrics-title">Core &amp; Swing Results</h2>
            <span>Each position layer keeps separate quantity, cost, fees and realized performance.</span>
          </div>
        </div>
        <div className="backtest-layer-metrics-grid">
          <section className="backtest-layer-column is-core" aria-label="Core position metrics">
            <h3>Core Position</h3>
            <LayerMetric label="Return Contribution" value={formatSignedPercentage(result.coreMetrics.returnContribution)} tone={getTone(result.coreMetrics.returnContribution)} />
            <LayerMetric label="Realized P/L" value={formatCurrency(result.coreMetrics.realizedProfitLoss)} tone={getTone(result.coreMetrics.realizedProfitLoss)} />
            <LayerMetric label="Unrealized P/L" value={formatCurrency(result.coreMetrics.unrealizedProfitLoss)} tone={getTone(result.coreMetrics.unrealizedProfitLoss)} />
            <LayerMetric label="Holding Days" value={String(result.coreMetrics.holdingDays)} />
            <LayerMetric label="Core BUY" value={String(result.coreMetrics.entryCount)} />
            <LayerMetric label="Core ADD" value={String(result.coreMetrics.addCount)} />
            <LayerMetric label="Core REDUCE" value={String(result.coreMetrics.reduceCount)} />
            <LayerMetric label="Core FULL EXIT" value={String(result.coreMetrics.fullExitCount)} />
            <LayerMetric label="Avg Holding Period" value={`${formatCompactNumber(result.coreMetrics.averageHoldingPeriod)} days`} />
            <LayerMetric label="Median Holding Period" value={`${formatCompactNumber(result.coreMetrics.medianHoldingPeriod)} days`} />
            <LayerMetric label="Average Exposure" value={`${formatCompactNumber(result.coreMetrics.averageExposure)}%`} />
            <LayerMetric label="Max Exposure" value={`${formatCompactNumber(result.coreMetrics.maxExposure)}%`} />
            <LayerMetric label="Avg Full Exit → BUY Gap" value={`${formatCompactNumber(result.coreMetrics.fullExitToNextBuyAverageGap)} days`} />
            <LayerMetric label="Min Full Exit → BUY Gap" value={`${formatCompactNumber(result.coreMetrics.fullExitToNextBuyMinimumGap)} days`} />
            <LayerMetric label="Full Exit Reasons" value={formatReasonCounts(result.coreStrategyDiagnostics.full_exit_reasons)} />
            <LayerMetric label="Reduce Reasons" value={formatReasonCounts(result.coreStrategyDiagnostics.reduce_reasons)} />
            <LayerMetric label="Re-entry Reasons" value={formatReasonCounts(result.coreStrategyDiagnostics.reentry_reasons)} />
          </section>
          <section className="backtest-layer-column is-swing" aria-label="Swing position metrics">
            <h3>Swing Trading</h3>
            <LayerMetric label="Return Contribution" value={formatSignedPercentage(result.swingMetrics.returnContribution)} tone={getTone(result.swingMetrics.returnContribution)} />
            <LayerMetric label="Realized P/L" value={formatCurrency(result.swingMetrics.realizedProfitLoss)} tone={getTone(result.swingMetrics.realizedProfitLoss)} />
            <LayerMetric label="Completed Cycles" value={String(result.swingMetrics.cycleCount)} />
            <LayerMetric label="Swing BUY" value={String(result.swingMetrics.entryCount)} />
            <LayerMetric label="Swing SELL" value={String(result.swingMetrics.exitCount)} />
            <LayerMetric label="Average Days / Cycle" value={formatCompactNumber(result.swingMetrics.averageDaysPerCycle, 1)} />
            <LayerMetric label="Median Days / Cycle" value={formatCompactNumber(result.swingMetrics.medianDaysPerCycle, 1)} />
            <LayerMetric label="1-bar Swing Cycles" value={String(result.swingMetrics.oneBarCycleCount)} />
            <LayerMetric label="Winning Swing Cycles" value={String(result.swingMetrics.profitableCycleCount)} />
            <LayerMetric label="Losing Swing Cycles" value={String(result.swingMetrics.losingCycleCount)} />
            <LayerMetric label="Swing Win Rate" value={formatPercentage(result.swingMetrics.winRate)} />
            <LayerMetric label="Average Swing Return" value={formatSignedPercentage(result.swingMetrics.averageReturn)} tone={getTone(result.swingMetrics.averageReturn)} />
            <LayerMetric label="Swing Total Fees" value={formatCurrency(result.swingMetrics.fees)} />
            <LayerMetric label="Swing Turnover" value={formatPercentage(result.swingMetrics.turnover)} />
          </section>
        </div>
      </section>

      <BacktestPriceSignalChart
        points={result.points}
        trades={result.trades}
        coreFastMa={result.config.coreFastMa}
        coreSlowMa={result.config.coreSlowMa}
        swingAverageType={result.parametersUsed?.swingAverageType || 'EMA10'}
      />
      <BacktestExposureChart points={result.points} />
      <BacktestLineChart variant="equity" points={result.points} />
      <BacktestLineChart variant="drawdown" points={result.points} />

      <section className="backtest-card backtest-comparison-card" aria-labelledby="backtest-comparison-title">
        <div className="backtest-card-header">
          <div>
            <p>Same prices and assumptions</p>
            <h2 id="backtest-comparison-title">Strategy Comparison</h2>
            <span>Buy and Hold, Core-Only and Hybrid use the same asset, dates, capital, fees and OHLCV source.</span>
          </div>
        </div>
        <div className="backtest-table-wrap">
          <table className="backtest-comparison-table">
            <caption className="sr-only">Backtest strategy comparison</caption>
            <thead>
              <tr>
                <th scope="col">Strategy</th>
                <th scope="col">Total Return</th>
                <th scope="col">Final Equity</th>
                <th scope="col">Max Drawdown</th>
                <th scope="col">Annualized Volatility</th>
                <th scope="col">Fees</th>
                <th scope="col">Orders</th>
              </tr>
            </thead>
            <tbody>
              {result.comparisons.map((comparison) => (
                <tr className={comparison.strategyId === 'core-swing-hybrid' ? 'is-hybrid' : ''} key={comparison.strategyId}>
                  <td data-label="Strategy"><strong>{comparison.strategy}</strong></td>
                  <td data-label="Total Return"><span className={getTone(comparison.totalReturn)}>{formatSignedPercentage(comparison.totalReturn)}</span></td>
                  <td data-label="Final Equity">{formatCurrency(comparison.finalEquity)}</td>
                  <td data-label="Max Drawdown">{formatPercentage(comparison.maximumDrawdown)}</td>
                  <td data-label="Annualized Volatility">{formatPercentage(comparison.annualizedVolatility)}</td>
                  <td data-label="Fees">{formatCurrency(comparison.totalFees)}</td>
                  <td data-label="Orders">{comparison.executedOrders}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="backtest-card backtest-summary-card" aria-labelledby="backtest-summary-title">
        <div className="backtest-card-header">
          <div>
            <p>Decision support</p>
            <h2 id="backtest-summary-title">Backtest Summary</h2>
            <span>Plain-English interpretation without assuming the Hybrid strategy is best.</span>
          </div>
        </div>
        <div className="backtest-summary-grid">
          <article>
            <span>Strategy result</span>
            <p>{result.summary.comparison || 'All strategies were calculated from the same real daily OHLCV.'}</p>
          </article>
          <article>
            <span>Drawdown risk</span>
            <p>{result.summary.drawdownRisk || 'Risk metrics are calculated from the daily Hybrid equity curve.'}</p>
          </article>
          <article>
            <span>Performance quality</span>
            <p>{result.summary.quality || 'Only completed Swing BUY-SELL cycles contribute to Swing win rate.'}</p>
          </article>
          <article>
            <span>Data source</span>
            <p>
              {(dataSource.source || 'market_data').replaceAll('_', ' ')} for {result.asset.symbol}; benchmark {result.benchmark.symbol}
              {dataSource.actual_start_date && dataSource.actual_end_date
                ? `, ${dataSource.actual_start_date} to ${dataSource.actual_end_date}`
                : ''}
            </p>
          </article>
        </div>
        <p className="backtest-summary-disclaimer">
          {result.summary.disclaimer || 'This backtest uses historical market data and does not guarantee future performance.'}
        </p>
      </section>

      <TradeHistoryTable trades={result.trades} />
    </section>
  )
}
