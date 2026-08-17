export default function ModelAgreement({ agreement }) {
  if (!agreement) {
    return <section className="prediction-card prediction-equal-card"><div className="prediction-card-header"><div><p>Consensus check</p><h2>Model Agreement</h2><span>Not implemented until real prediction models are available.</span></div></div></section>
  }
  const tone = agreement.agreement === 'Strong' ? 'positive' : agreement.agreement === 'Weak' ? 'negative' : 'warning'

  return (
    <section className="prediction-card prediction-equal-card" aria-labelledby="prediction-agreement-title">
      <div className="prediction-card-header">
        <div>
          <p>Consensus check</p>
          <h2 id="prediction-agreement-title">Model Agreement</h2>
          <span>{agreement.summary}</span>
        </div>
        <strong className={`prediction-level-chip is-${tone}`}>{agreement.agreement}</strong>
      </div>

      <dl className="prediction-compact-metrics">
        <div>
          <dt>Dominant Direction</dt>
          <dd>{agreement.dominantDirection}</dd>
        </div>
        <div>
          <dt>Models Aligned</dt>
          <dd>{agreement.dominantCount} of {agreement.modelCount}</dd>
        </div>
        <div>
          <dt>Probability Range</dt>
          <dd>{agreement.probabilityRange}</dd>
        </div>
        <div>
          <dt>Significant Disagreement</dt>
          <dd>{agreement.significantDisagreement ? 'Yes' : 'No'}</dd>
        </div>
      </dl>
    </section>
  )
}
