function formatCurrency(value) {
  return `$${value.toFixed(2)}`
}

function formatSignedPercent(value) {
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}

export default function ScenarioSimulation({ scenarios }) {
  if (!scenarios.length) {
    return <section className="prediction-section"><div className="prediction-result-heading"><div><p>Conditional outcomes</p><h2 id="prediction-scenarios-title">Scenario Simulation</h2><span>Not implemented until a real prediction model produces a forecast distribution.</span></div></div></section>
  }
  return (
    <section className="prediction-section" aria-labelledby="prediction-scenarios-title">
      <div className="prediction-result-heading">
        <div>
          <p>Conditional outcomes</p>
          <h2 id="prediction-scenarios-title">Scenario Simulation</h2>
          <span>Mutually exclusive simulated outcomes whose probabilities sum to 100%.</span>
        </div>
      </div>

      <div className="prediction-scenario-grid">
        {scenarios.map((scenario) => (
          <article className={`prediction-card prediction-scenario-card is-${scenario.key}`} key={scenario.key}>
            <div className="prediction-scenario-heading">
              <div>
                <p>{scenario.key} case</p>
                <h3>{scenario.title}</h3>
              </div>
              <strong>{scenario.probability}%</strong>
            </div>
            <dl>
              <div>
                <dt>Estimated Price</dt>
                <dd>{formatCurrency(scenario.estimatedPrice)}</dd>
              </div>
              <div>
                <dt>Potential Return</dt>
                <dd>{formatSignedPercent(scenario.potentialReturn)}</dd>
              </div>
              <div>
                <dt>Scenario Probability</dt>
                <dd>{scenario.probability}%</dd>
              </div>
            </dl>
            <div className="prediction-scenario-assumptions">
              <strong>Main Assumptions</strong>
              <span>{scenario.assumptions}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
