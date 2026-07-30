export default function ForecastReliability({ reliability }) {
  const summary = reliability.summary.replace(
    /\d+ of 4 models share the dominant direction/,
    'the underlying forecast signals show mixed consistency',
  )
  const displayItems = reliability.items.map((item) => {
    if (item.label === 'Model Agreement') {
      return {
        ...item,
        label: 'Forecast Consistency',
        detail: `${item.value} consistency across the underlying forecast signals.`,
      }
    }
    if (item.label === 'Historical Test Performance') {
      return {
        ...item,
        label: 'Simulated Reliability',
        detail: `Simulated validation evidence is ${item.value.toLowerCase()} for the current configuration.`,
      }
    }
    return item
  })

  return (
    <section className="prediction-card prediction-equal-card" aria-labelledby="prediction-reliability-title">
      <div className="prediction-card-header">
        <div>
          <p>Uncertainty review</p>
          <h2 id="prediction-reliability-title">Forecast Reliability</h2>
          <span>{summary}</span>
        </div>
      </div>

      <div className="prediction-reliability-list">
        {displayItems.map((item) => (
          <div className="prediction-reliability-row" key={item.label}>
            <div>
              <strong>{item.label}</strong>
              <span>{item.detail}</span>
            </div>
            <b className={`is-${item.tone}`}>{item.value}</b>
            <i aria-label={`${item.label}: ${item.value}`}>
              <span className={`is-${item.tone}`} style={{ width: item.value === 'High' ? '82%' : item.value === 'Medium' ? '58%' : '34%' }} />
            </i>
          </div>
        ))}
      </div>
    </section>
  )
}
