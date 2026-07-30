import {
  formatPercentage,
  formatSignedPercentage,
} from '../portfolio/portfolioMath'
import BacktestLineChart from './BacktestLineChart'
import TradeHistoryTable from './TradeHistoryTable'

function getTone(value, positiveThreshold = 0) {
  if (value > positiveThreshold) return 'is-positive'
  if (value < 0) return 'is-negative'
  return 'is-neutral'
}

export default function BacktestResults({ result }) {
  const metrics = [
    {
      label: 'Total Return',
      value: formatSignedPercentage(result.metrics.totalReturn),
      detail: `Benchmark ${formatSignedPercentage(result.metrics.benchmarkReturn)}`,
      tone: getTone(result.metrics.totalReturn),
    },
    {
      label: 'Annualised Return',
      value: formatSignedPercentage(result.metrics.annualisedReturn),
      detail: 'Annual equivalent',
      tone: getTone(result.metrics.annualisedReturn),
    },
    {
      label: 'Maximum Drawdown',
      value: formatSignedPercentage(result.metrics.maximumDrawdown),
      detail: 'Peak-to-trough decline',
      tone: Math.abs(result.metrics.maximumDrawdown) <= 10 ? 'is-neutral' : 'is-negative',
    },
    {
      label: 'Win Rate',
      value: formatPercentage(result.metrics.winRate),
      detail: 'Profitable completed trades',
      tone: result.metrics.winRate >= 55 ? 'is-positive' : result.metrics.winRate < 45 ? 'is-negative' : 'is-neutral',
    },
    {
      label: 'Sharpe Ratio',
      value: result.metrics.sharpeRatio.toFixed(2),
      detail: 'Risk-adjusted return',
      tone: result.metrics.sharpeRatio >= 1 ? 'is-positive' : result.metrics.sharpeRatio < 0.5 ? 'is-negative' : 'is-neutral',
    },
    {
      label: 'Number of Trades',
      value: String(result.metrics.numberOfTrades),
      detail: 'Simulated executions',
      tone: 'is-neutral',
    },
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

      <BacktestLineChart variant="equity" points={result.points} />
      <BacktestLineChart variant="drawdown" points={result.points} />

      <section className="backtest-card backtest-summary-card" aria-labelledby="backtest-summary-title">
        <div className="backtest-card-header">
          <div>
            <p>Decision support</p>
            <h2 id="backtest-summary-title">Backtest Summary</h2>
            <span>Plain-English interpretation of this simulated historical result.</span>
          </div>
        </div>
        <div className="backtest-summary-grid">
          <article>
            <span>Benchmark comparison</span>
            <p>{result.summary.comparison}</p>
          </article>
          <article>
            <span>Drawdown risk</span>
            <p>{result.summary.drawdownRisk}</p>
          </article>
          <article>
            <span>Performance quality</span>
            <p>{result.summary.quality}</p>
          </article>
        </div>
        <p className="backtest-summary-disclaimer">{result.summary.disclaimer}</p>
      </section>

      <TradeHistoryTable trades={result.trades} />
    </section>
  )
}
