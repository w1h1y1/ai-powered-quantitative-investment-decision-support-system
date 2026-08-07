export default function TechnicalIndicators({ indicators }) {
  const safeIndicators = indicators ?? { signal: 'N/A', score: null, items: [] }
  const hasScore = Number.isFinite(safeIndicators.score)
  const scoreLabel = hasScore ? safeIndicators.score : 'N/A'
  const trackWidth = hasScore ? `${Math.max(0, Math.min(safeIndicators.score, 100))}%` : '0%'

  return (
    <section className="dashboard-panel indicators-panel" aria-labelledby="indicators-title">
      <div className="panel-header">
        <div>
          <p>{safeIndicators.sourceLabel ?? 'Real OHLCV signal snapshot'}</p>
          <h2 id="indicators-title">Technical Indicators</h2>
        </div>
        <span className="signal-badge">{safeIndicators.signal}</span>
      </div>

      <div className="signal-score">
        <div className="signal-score-copy">
          <span>Composite signal</span>
          <strong>{scoreLabel}{hasScore && <small>/100</small>}</strong>
        </div>
        <div className="signal-track" aria-label={hasScore ? `Composite signal ${safeIndicators.score} out of 100` : 'Composite signal unavailable'}>
          <span style={{ width: trackWidth }} />
        </div>
      </div>

      <div className="indicator-list">
        {safeIndicators.notice && (
          <article className="indicator-item" role="status">
            <div className="indicator-row">
              <div>
                <span>Data status</span>
                <strong>{safeIndicators.notice}</strong>
              </div>
              <span className="indicator-signal is-neutral">Info</span>
            </div>
          </article>
        )}
        {safeIndicators.items.map((indicator) => (
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
