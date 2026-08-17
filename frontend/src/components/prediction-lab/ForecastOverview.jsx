import Icon from '../Icon'

function formatSignedPercent(value) {
  if (!Number.isFinite(value)) return 'N/A'
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}

function formatCurrency(value) {
  if (!Number.isFinite(value)) return 'N/A'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

function getProbabilityTone(value) {
  return value >= 58 ? 'positive' : value <= 42 ? 'negative' : 'neutral'
}

export default function ForecastOverview({ forecast }) {
  const classificationUnavailable = !forecast.predictionAvailable
  const regressionUnavailable = !forecast.regressionPredictionAvailable
  const items = [
    {
      label: `${forecast.configuration.directionHorizonLabel} Direction`,
      value: classificationUnavailable ? 'N/A' : forecast.predictedDirection,
      icon: 'trend',
      tone: classificationUnavailable ? 'neutral' : forecast.predictedDirection === 'Up' ? 'positive' : forecast.predictedDirection === 'Down' ? 'negative' : 'neutral',
    },
    {
      label: `${forecast.configuration.directionHorizonLabel} Probability of Increase`,
      value: classificationUnavailable || !Number.isFinite(forecast.probabilityIncrease)
        ? 'N/A'
        : `${forecast.probabilityIncrease.toFixed(1)}%`,
      icon: 'target',
      tone: classificationUnavailable ? 'neutral' : getProbabilityTone(forecast.probabilityIncrease),
    },
    {
      label: `${forecast.configuration.returnHorizonLabel} Expected Return`,
      value: regressionUnavailable ? 'N/A' : formatSignedPercent(forecast.expectedReturn),
      icon: 'market',
      tone: regressionUnavailable ? 'neutral' : forecast.expectedReturn > 0.2 ? 'positive' : forecast.expectedReturn < -0.2 ? 'negative' : 'neutral',
    },
    {
      label: `${forecast.configuration.returnHorizonLabel} Predicted Price`,
      value: regressionUnavailable ? 'N/A' : formatCurrency(forecast.expectedPrice),
      icon: 'portfolio',
      tone: regressionUnavailable ? 'neutral' : 'positive',
    },
    {
      label: 'Direction Confidence',
      value: classificationUnavailable ? 'N/A' : forecast.confidence,
      icon: 'shield',
      tone: classificationUnavailable ? 'neutral' : forecast.confidence === 'High' ? 'positive' : forecast.confidence === 'Low' ? 'negative' : 'warning',
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
      {(classificationUnavailable || regressionUnavailable) && (
        <div className="prediction-output-status-grid" aria-label="Prediction availability details">
          {classificationUnavailable && (
            <article className="prediction-output-status is-unavailable">
              <strong>Direction Prediction Unavailable</strong>
              <span>{forecast.classificationPredictionMessage}</span>
            </article>
          )}
          {regressionUnavailable && (
            <article className="prediction-output-status is-unavailable">
              <strong>Return Prediction Unavailable</strong>
              <span>{forecast.regressionPredictionMessage}</span>
            </article>
          )}
        </div>
      )}
    </section>
  )
}
