const importanceWidth = {
  High: '82%',
  Medium: '58%',
  Low: '34%',
}

export default function FeatureInfluence({ features }) {
  return (
    <section className="prediction-card prediction-equal-card" aria-labelledby="prediction-features-title">
      <div className="prediction-card-header">
        <div>
          <p>Rule inputs</p>
          <h2 id="prediction-features-title">Feature Influence</h2>
          <span>Illustrative feature influence for the deterministic mock forecast.</span>
        </div>
      </div>

      <ul className="prediction-feature-list">
        {features.map((feature) => (
          <li key={feature.name}>
            <div className="prediction-feature-copy">
              <strong>{feature.name}</strong>
              <span>{feature.explanation}</span>
            </div>
            <div className="prediction-feature-status">
              <b className={`is-${feature.direction.toLowerCase()}`}>{feature.direction}</b>
              <small>{feature.importance} importance</small>
              <i aria-hidden="true"><span style={{ width: importanceWidth[feature.importance] }} /></i>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
