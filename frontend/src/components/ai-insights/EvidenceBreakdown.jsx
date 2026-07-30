function ToneBadge({ tone, children }) {
  return <span className={`ai-insights-tone-badge is-${tone}`}>{children}</span>
}

function EvidenceCard({ title, eyebrow, className = '', children }) {
  return (
    <article className={`ai-insights-card ai-insights-evidence-card ${className}`.trim()}>
      <div className="ai-insights-card-header">
        <div>
          <p>{eyebrow}</p>
          <h2>{title}</h2>
        </div>
      </div>
      {children}
    </article>
  )
}

function PredictionEvidence({ evidence, onAnalysePredictionAsset }) {
  const metrics = evidence?.metrics?.filter((metric) => (
    metric.label !== 'Selected Model' && metric.label !== 'Model Agreement'
  )) ?? []
  const explanation = evidence?.explanation?.replace('model agreement', 'forecast consistency')

  if (!metrics.length) {
    return (
      <div className="ai-insights-prediction-note">
        <p className="ai-insights-muted-note">{explanation ?? 'No forecast context is currently available.'}</p>
        {evidence?.status === 'mismatch' && evidence.assetSymbol && (
          <button type="button" onClick={() => onAnalysePredictionAsset(evidence.assetSymbol)}>
            Analyse {evidence.assetSymbol} instead
          </button>
        )}
      </div>
    )
  }

  return (
    <>
      <MetricList metrics={metrics} explanation={explanation} />
      {evidence.status === 'mismatch' && evidence.assetSymbol && (
        <div className="ai-insights-prediction-note">
          <button type="button" onClick={() => onAnalysePredictionAsset(evidence.assetSymbol)}>
            Analyse {evidence.assetSymbol} instead
          </button>
        </div>
      )}
    </>
  )
}

function SignalList({ items }) {
  return (
    <ul className="ai-insights-signal-list">
      {items.map((item) => (
        <li key={item.key ?? item.label}>
          <div>
            <strong>{item.label}</strong>
            <span>{item.explanation}</span>
          </div>
          <div>
            <b>{item.value}</b>
            <ToneBadge tone={item.tone}>{item.assessment}</ToneBadge>
          </div>
        </li>
      ))}
    </ul>
  )
}

function MetricList({ metrics, explanation }) {
  if (!metrics.length) {
    return <p className="ai-insights-muted-note">{explanation}</p>
  }

  return (
    <>
      <dl className="ai-insights-metric-list">
        {metrics.map((metric) => (
          <div key={metric.label}>
            <dt>{metric.label}</dt>
            <dd>{metric.value}</dd>
          </div>
        ))}
      </dl>
      <p className="ai-insights-card-note">{explanation}</p>
    </>
  )
}

export default function EvidenceBreakdown({
  insight,
  predictionEvidenceOverride,
  onAnalysePredictionAsset,
}) {
  const predictionEvidence = predictionEvidenceOverride ?? insight.predictionEvidence ?? {
    status: 'unavailable',
    metrics: [],
    explanation: 'No forecast context is currently available.',
  }

  return (
    <section className="ai-insights-evidence-section" aria-labelledby="ai-insights-evidence-title">
      <div className="ai-insights-result-heading">
        <p>Supporting evidence</p>
        <h2 id="ai-insights-evidence-title">Evidence Breakdown</h2>
      </div>

      <div className="ai-insights-evidence-grid">
        <div className="ai-insights-evidence-row">
          <EvidenceCard title="Technical Signals" eyebrow="Technical analysis">
            <SignalList items={insight.technicalSignals} />
          </EvidenceCard>

          <EvidenceCard title="Portfolio Context" eyebrow="Portfolio risk">
            <MetricList
              metrics={insight.portfolioContext.metrics}
              explanation={insight.portfolioContext.explanation}
            />
          </EvidenceCard>
        </div>

        <div className="ai-insights-evidence-row">
          <EvidenceCard title="Backtest Evidence" eyebrow="Strategy evidence">
            <MetricList
              metrics={insight.backtestEvidence.metrics}
              explanation={insight.backtestEvidence.explanation}
            />
          </EvidenceCard>

          <EvidenceCard title="Forecast Context" eyebrow="PREDICTION LAB CONTEXT">
            <PredictionEvidence
              evidence={predictionEvidence}
              onAnalysePredictionAsset={onAnalysePredictionAsset}
            />
          </EvidenceCard>
        </div>

        <div className="ai-insights-evidence-row is-single">
          <EvidenceCard title="Market Context" eyebrow="Market backdrop">
            <SignalList items={insight.marketContext} />
          </EvidenceCard>
        </div>
      </div>
    </section>
  )
}
