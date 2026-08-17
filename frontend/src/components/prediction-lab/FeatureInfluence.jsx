const importanceWidth = {
  High: '82%',
  Medium: '58%',
  Low: '34%',
}

function formatValue(value, suffix = '') {
  return Number.isFinite(value) ? `${value.toFixed(2)}${suffix}` : 'N/A'
}

function formatVolumeTrend(volume) {
  if (!volume?.direction || volume.direction === 'unavailable') return 'N/A'
  const direction = volume?.direction
    ? `${volume.direction.charAt(0).toUpperCase()}${volume.direction.slice(1)}`
    : 'N/A'
  return Number.isFinite(volume?.percent_change)
    ? `${direction} (${volume.percent_change >= 0 ? '+' : ''}${volume.percent_change.toFixed(2)}%)`
    : direction
}

export default function FeatureInfluence({ features, technicalIndicators }) {
  if (!features.length) {
    const volume = technicalIndicators?.volume_trend ?? {}
    const metrics = [
      ['MA5', formatValue(technicalIndicators?.ma5)],
      ['MA10', formatValue(technicalIndicators?.ma10)],
      ['MA20', formatValue(technicalIndicators?.ma20)],
      ['MA60', formatValue(technicalIndicators?.ma60)],
      ['RSI', formatValue(technicalIndicators?.rsi)],
      ['MACD', formatValue(technicalIndicators?.macd)],
      ['MACD Signal', formatValue(technicalIndicators?.macd_signal)],
      ['ATR', formatValue(technicalIndicators?.atr)],
      ['Recent Return', formatValue(technicalIndicators?.recent_return, '%')],
      ['Annualized Volatility', formatValue(technicalIndicators?.volatility, '%')],
      ['Volume Trend', formatVolumeTrend(volume)],
    ]
    return (
      <section className="prediction-card prediction-technical-card" aria-labelledby="prediction-features-title">
        <div className="prediction-card-header"><div><p>Calculated from real OHLCV</p><h2 id="prediction-features-title">Technical Indicators</h2><span>Latest indicator values for the selected historical lookback.</span></div></div>
        <dl className="prediction-technical-grid">{metrics.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      </section>
    )
  }
  return (
    <section className="prediction-card prediction-equal-card" aria-labelledby="prediction-features-title">
      <div className="prediction-card-header">
        <div>
          <p>Model inputs</p>
          <h2 id="prediction-features-title">Feature Influence</h2>
          <span>Feature diagnostics returned by the trained prediction model.</span>
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
