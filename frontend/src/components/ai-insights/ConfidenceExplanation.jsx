const levelWidths = {
  Low: '34%',
  Medium: '66%',
  High: '100%',
}

export default function ConfidenceExplanation({ explanation }) {
  return (
    <section className="ai-insights-card ai-insights-confidence-card" aria-labelledby="ai-insights-confidence-title">
      <div className="ai-insights-card-header">
        <div>
          <p>Confidence rationale</p>
          <h2 id="ai-insights-confidence-title">Confidence Explanation</h2>
        </div>
      </div>

      <p className="ai-insights-confidence-body">{explanation.body}</p>

      <div className="ai-insights-confidence-list">
        {explanation.factors.map((factor) => (
          <div className="ai-insights-confidence-row" key={factor.label}>
            <div>
              <strong>{factor.label}</strong>
              <span>{factor.detail.replace('model agreement', 'forecast consistency')}</span>
            </div>
            <div className="ai-insights-confidence-meter" aria-label={`${factor.label}: ${factor.level}`}>
              <span className={`is-${factor.tone}`} style={{ width: levelWidths[factor.level] }} />
            </div>
            <b className={`is-${factor.tone}`}>{factor.level}</b>
          </div>
        ))}
      </div>
    </section>
  )
}
