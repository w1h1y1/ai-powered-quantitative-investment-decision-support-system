function formatCurrency(value) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

export default function PriceForecastSummary({ forecast }) {
  const priceSummary = forecast.priceSummary.replace(
    'The selected model indicates',
    'The deterministic mock forecast indicates',
  )
  const metrics = [
    ['Current Price', formatCurrency(forecast.currentPrice)],
    ['Expected Price', formatCurrency(forecast.expectedPrice)],
    ['Lower Forecast Bound', formatCurrency(forecast.forecastRange.lower)],
    ['Upper Forecast Bound', formatCurrency(forecast.forecastRange.upper)],
    ['Expected Volatility', forecast.expectedVolatility],
    ['Forecast Horizon', forecast.configuration.horizonLabel],
  ]

  return (
    <section className="prediction-card prediction-price-summary" aria-labelledby="prediction-price-summary-title">
      <div className="prediction-card-header">
        <div>
          <p>Price distribution</p>
          <h2 id="prediction-price-summary-title">Price Forecast Summary</h2>
          <span>{forecast.asset.symbol} simulated price range from the current deterministic mock forecast.</span>
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
      <p className="prediction-card-note">{priceSummary}</p>
    </section>
  )
}
