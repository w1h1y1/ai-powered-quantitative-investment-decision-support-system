import Icon from '../Icon'

function formatSignedPercent(value) {
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}

function getProbabilityTone(value) {
  return value >= 58 ? 'positive' : value <= 42 ? 'negative' : 'neutral'
}

export default function ForecastOverview({ forecast }) {
  const items = [
    {
      label: 'Predicted Direction',
      value: forecast.predictedDirection,
      icon: 'trend',
      tone: forecast.predictedDirection === 'Up' ? 'positive' : forecast.predictedDirection === 'Down' ? 'negative' : 'neutral',
    },
    {
      label: 'Probability of Increase',
      value: `${forecast.probabilityIncrease}%`,
      icon: 'target',
      tone: getProbabilityTone(forecast.probabilityIncrease),
    },
    {
      label: 'Expected Return',
      value: formatSignedPercent(forecast.expectedReturn),
      icon: 'market',
      tone: forecast.expectedReturn > 0.2 ? 'positive' : forecast.expectedReturn < -0.2 ? 'negative' : 'neutral',
    },
    {
      label: 'Forecast Confidence',
      value: forecast.confidence,
      icon: 'shield',
      tone: forecast.confidence === 'High' ? 'positive' : forecast.confidence === 'Low' ? 'negative' : 'warning',
    },
  ]

  return (
    <section className="prediction-overview" aria-labelledby="prediction-overview-title">
      <div className="prediction-result-heading">
        <div>
          <p>Probabilistic result</p>
          <h2 id="prediction-overview-title">Forecast Overview</h2>
        </div>
      </div>
      <div className="prediction-overview-grid">
        {items.map((item) => (
          <article className={`prediction-overview-tile is-${item.tone}`} key={item.label}>
            <span className="prediction-overview-icon" aria-hidden="true"><Icon name={item.icon} /></span>
            <div>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
