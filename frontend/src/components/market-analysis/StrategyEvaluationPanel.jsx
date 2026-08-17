import {
  formatAllowNewLong,
  formatEvaluationMoney,
  formatEvaluationPercent,
  formatStrategyLabel,
  formatStrategyModeLabel,
  formatTradeCount,
  formatUnavailableReason,
} from './strategyEvaluationModel'

function Metric({ label, tone = '', value }) {
  return (
    <div className="strategy-evaluation-metric">
      <span>{label}</span>
      <strong className={tone ? `is-${tone}` : ''}>{value}</strong>
    </div>
  )
}

function StrategyBadge({ strategy }) {
  const tone = strategy === 'risk_off'
    ? 'warning'
    : strategy === 'mean_reversion'
      ? 'neutral'
      : 'positive'
  return (
    <strong className={`strategy-evaluation-badge is-${tone}`}>
      {formatStrategyLabel(strategy)}
    </strong>
  )
}

function getMetricTone(value, positiveThreshold = 0) {
  if (value > positiveThreshold) return 'positive'
  if (value < 0) return 'negative'
  return ''
}

function displayDataSource(source) {
  const normalized = String(source ?? '').trim().toLowerCase()
  if (normalized === 'database_cache') return 'Cached market data'
  if (normalized === 'twelve_data') return 'Twelve Data'
  return source || 'N/A'
}

function HistoricalEvaluation({ evaluation }) {
  const metrics = evaluation.metrics
  const window = evaluation.evaluationWindow
  const dataSource = evaluation.dataSource || {}
  const strategyParameters = evaluation.strategyParameters || {}

  return (
    <>
      <div className="strategy-evaluation-metrics-grid" aria-label="Historical strategy evaluation metrics">
        <article className={`strategy-evaluation-metric-card ${getMetricTone(metrics.totalReturn)}`}>
          <span>Total Return</span>
          <strong>{formatEvaluationPercent(metrics.totalReturn, { signed: true })}</strong>
          <small>Historical final equity versus initial capital</small>
        </article>
        <article className={`strategy-evaluation-metric-card ${getMetricTone(metrics.finalEquity - metrics.initialCapital)}`}>
          <span>Final Equity</span>
          <strong>{formatEvaluationMoney(metrics.finalEquity)}</strong>
          <small>Cash plus strategy holdings</small>
        </article>
        <article className={`strategy-evaluation-metric-card ${metrics.maximumDrawdown > 10 ? 'is-negative' : ''}`}>
          <span>Maximum Drawdown</span>
          <strong>{formatEvaluationPercent(metrics.maximumDrawdown)}</strong>
          <small>Largest peak-to-trough decline</small>
        </article>
        <article className="strategy-evaluation-metric-card">
          <span>Annualized Volatility</span>
          <strong>{formatEvaluationPercent(metrics.annualizedVolatility)}</strong>
          <small>Daily equity volatility annualized</small>
        </article>
        <article className="strategy-evaluation-metric-card">
          <span>Executed Orders</span>
          <strong>{formatTradeCount(metrics.executedOrderCount)}</strong>
          <small>All strategy executions</small>
        </article>
        <article className="strategy-evaluation-metric-card">
          <span>Total Fees</span>
          <strong>{formatEvaluationMoney(metrics.totalFees)}</strong>
          <small>All executed order fees</small>
        </article>
      </div>

      {(window || dataSource.source || strategyParameters.strategy) && (
        <footer className="strategy-evaluation-footer">
          {window?.start_date && window?.end_date && (
            <span>Evaluation window: {window.start_date} to {window.end_date}</span>
          )}
          {strategyParameters.strategy && (
            <span>Strategy: {strategyParameters.strategy}</span>
          )}
          <span>Data source: {displayDataSource(dataSource.source)}</span>
        </footer>
      )}
    </>
  )
}

function HistoricalUnavailable({ evaluation }) {
  const isNotApplicable = evaluation.evaluationStatus === 'not_applicable'
  const title = isNotApplicable ? 'Not Applicable' : 'Unavailable'
  const reason = evaluation.evaluationUnavailableReason
    ? formatUnavailableReason(evaluation.evaluationUnavailableReason)
    : isNotApplicable
      ? 'Historical evaluation does not apply to the selected strategy.'
      : 'Historical evaluation is currently unavailable.'

  return (
    <div className="strategy-evaluation-unavailable" aria-live="polite">
      <strong className={`is-${isNotApplicable ? 'neutral' : 'warning'}`}>{title}</strong>
      <p>{reason}</p>
    </div>
  )
}

function LoadingState({ symbol }) {
  return (
    <section className="market-panel strategy-evaluation-panel" aria-busy="true" aria-live="polite">
      <div className="market-panel-header strategy-evaluation-header">
        <div>
          <p>Strategy Evaluation</p>
          <h2>Loading strategy evaluation for {symbol}...</h2>
        </div>
      </div>
      <div className="strategy-evaluation-skeleton" aria-hidden="true">
        <i />
        <i />
        <i />
        <i />
        <i />
        <i />
      </div>
    </section>
  )
}

function ErrorState({ error, onRetry, symbol }) {
  return (
    <section className="market-panel strategy-evaluation-panel strategy-evaluation-message" aria-live="assertive" role="alert">
      <div>
        <p>Strategy Evaluation</p>
        <h2>Strategy evaluation temporarily unavailable</h2>
        <span>{error || `Unable to load strategy evaluation for ${symbol}.`}</span>
      </div>
      {onRetry && <button type="button" onClick={onRetry}>Retry</button>}
    </section>
  )
}

function SelectionUnavailable({ evaluation, symbol }) {
  const reason = evaluation.reason[0]
    || formatUnavailableReason(
      evaluation.evaluationUnavailableReason
        || evaluation.marketRegimeUnavailableReason
        || 'strategy_selection_unavailable',
    )
  return (
    <section className="market-panel strategy-evaluation-panel strategy-evaluation-message" aria-live="polite">
      <div>
        <p>Strategy Evaluation</p>
        <h2>Strategy selection unavailable for {symbol}</h2>
        <span>{reason}</span>
      </div>
    </section>
  )
}

export default function StrategyEvaluationPanel({
  evaluation,
  error,
  isLoading,
  onRetry,
  symbol,
}) {
  if (isLoading) return <LoadingState symbol={symbol} />
  if (error) return <ErrorState error={error} onRetry={onRetry} symbol={symbol} />
  if (!evaluation) return null
  if (!evaluation.selectionAvailable) {
    return <SelectionUnavailable evaluation={evaluation} symbol={symbol} />
  }

  return (
    <section className={`market-panel strategy-evaluation-panel${evaluation.riskOff ? ' is-risk-off' : ''}`} aria-live="polite">
      <div className="market-panel-header strategy-evaluation-header">
        <div>
          <p>Strategy Evaluation</p>
          <div className="strategy-evaluation-title-row">
            <h2>{evaluation.symbol}</h2>
            <StrategyBadge strategy={evaluation.selectedStrategy} />
            <span className="strategy-evaluation-confidence">
              Confidence: {evaluation.selectionConfidence}
            </span>
          </div>
        </div>
      </div>

      <div className="strategy-evaluation-grid">
        <article className="strategy-evaluation-selection-card">
          <header>
            <span>01</span>
            <h3>Strategy Selection</h3>
          </header>
          <Metric label="Selected Strategy" value={evaluation.strategyLabel} />
          <Metric label="Strategy Mode" value={evaluation.strategyModeLabel} />
          <Metric label="Execution Mode" value={evaluation.executionModeLabel} />
          <Metric
            label="Allow New Long"
            tone={evaluation.allowNewLong === false ? 'warning' : evaluation.allowNewLong === true ? 'positive' : ''}
            value={formatAllowNewLong(evaluation.allowNewLong)}
          />
          <Metric label="Selection Confidence" value={evaluation.selectionConfidence} />
        </article>

        <article className="strategy-evaluation-historical-card">
          <header>
            <span>02</span>
            <h3>Historical Strategy Evaluation</h3>
          </header>
          {evaluation.evaluationAvailable ? (
            <HistoricalEvaluation evaluation={evaluation} />
          ) : (
            <HistoricalUnavailable evaluation={evaluation} />
          )}
        </article>

        {evaluation.reason.length > 0 && (
          <article className="strategy-evaluation-reason-card">
            <header>
              <p>Rationale</p>
              <h3>Why this strategy?</h3>
            </header>
            <ol>
              {evaluation.reason.map((item, index) => (
                <li key={`${index}-${item}`}>{item}</li>
              ))}
            </ol>
          </article>
        )}
      </div>
    </section>
  )
}
