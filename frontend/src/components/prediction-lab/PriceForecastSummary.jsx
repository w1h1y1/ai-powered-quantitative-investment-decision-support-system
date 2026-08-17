function formatCurrency(value) {
  if (!Number.isFinite(value)) return 'N/A'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

function formatSignedPercent(value) {
  if (!Number.isFinite(value)) return 'N/A'
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

export default function PriceForecastSummary({ forecast }) {
  const showForecastSummary = forecast.predictionAvailable
    || forecast.regressionPredictionAvailable
    || Boolean(forecast.modelPerformance)
  const metrics = !showForecastSummary ? [
    ['Current Price', formatCurrency(forecast.currentPrice)],
    ['Latest Market Date', forecast.latestMarketDate],
    ['Historical Bars', String(forecast.historicalDataCount)],
    ['Annualized Volatility', Number.isFinite(forecast.technicalIndicators?.volatility)
      ? `${forecast.technicalIndicators.volatility.toFixed(2)}%`
      : 'Not available'],
    ['Direction Horizon', forecast.configuration.directionHorizonLabel],
    ['Return Horizon', forecast.configuration.returnHorizonLabel],
    ['Market Data Source', forecast.marketData?.source ?? 'Not available'],
  ] : [
    ['Current Price', formatCurrency(forecast.currentPrice)],
    [`${forecast.configuration.returnHorizonLabel} Predicted Price`, formatCurrency(forecast.expectedPrice)],
    [`${forecast.configuration.returnHorizonLabel} Expected Return`, formatSignedPercent(forecast.expectedReturn)],
    ['Classification Model', forecast.predictionAvailable
      ? forecast.selectedModel
      : 'Unavailable (quality gate)'],
    ['Regression Model', forecast.regressionPredictionAvailable
      ? forecast.regressionModel
      : forecast.selectedRegressionCandidateModel
        ? `${forecast.selectedRegressionCandidateModel} (not published)`
        : 'Unavailable'],
    ['Direction Horizon', forecast.configuration.directionHorizonLabel],
    ['Return Horizon', forecast.configuration.returnHorizonLabel],
  ]

  return (
    <section className="prediction-card prediction-price-summary" aria-labelledby="prediction-price-summary-title">
      <div className="prediction-card-header">
        <div>
          <p>{showForecastSummary ? 'Price distribution' : 'Real market data'}</p>
          <h2 id="prediction-price-summary-title">{showForecastSummary ? 'Price Forecast Summary' : 'Market Snapshot'}</h2>
          <span>{showForecastSummary ? forecast.asset.symbol : `${forecast.asset.symbol} real daily OHLCV summary.`}</span>
        </div>
        <strong className="prediction-asset-chip">{forecast.asset.type}</strong>
      </div>

      <dl className="prediction-metric-grid">
        {metrics.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {showForecastSummary && forecast.priceSummary && (
        <p className="prediction-card-note">
          {!forecast.regressionPredictionAvailable && <strong>Regression Prediction Unavailable. </strong>}
          {forecast.priceSummary}
        </p>
      )}
    </section>
  )
}
