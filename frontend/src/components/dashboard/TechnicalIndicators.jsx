export default function TechnicalIndicators({ indicators }) {
  return (
    <section className="dashboard-panel indicators-panel" aria-labelledby="indicators-title">
      <div className="panel-header">
        <div>
          <p>Demo signal snapshot</p>
          <h2 id="indicators-title">Technical Indicators</h2>
        </div>
        <span className="signal-badge">{indicators.signal}</span>
      </div>

      <div className="signal-score">
        <div className="signal-score-copy">
          <span>Composite signal</span>
          <strong>{indicators.score}<small>/100</small></strong>
        </div>
        <div className="signal-track" aria-label={`Composite signal ${indicators.score} out of 100`}>
          <span style={{ width: `${indicators.score}%` }} />
        </div>
      </div>

      <div className="indicator-list">
        {indicators.items.map((indicator) => (
          <article className="indicator-item" key={indicator.name}>
            <div className="indicator-row">
              <div>
                <span>{indicator.name}</span>
                <strong>{indicator.value}</strong>
              </div>
              <span className={`indicator-signal is-${indicator.tone}`}>{indicator.signal}</span>
            </div>
            <div className="indicator-track" aria-hidden="true">
              <span className={`is-${indicator.tone}`} style={{ width: `${indicator.level}%` }} />
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
