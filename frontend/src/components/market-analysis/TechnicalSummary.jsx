import { useMemo } from 'react'
import { buildTechnicalSummary } from './chartMath'

export default function TechnicalSummary({ history }) {
  const items = useMemo(
    () => buildTechnicalSummary(history.candles, history.indicators),
    [history.candles, history.indicators],
  )

  return (
    <section className="market-panel technical-summary-panel" aria-labelledby="technical-summary-title">
      <div className="technical-summary-header">
        <div>
          <p>Decision support snapshot</p>
          <h2 id="technical-summary-title">Technical Summary</h2>
        </div>
        <span>Market data - Descriptive signals, not a forecast</span>
      </div>

      <dl className="technical-summary-grid">
        {items.map((item) => (
          <div key={item.label}>
            <dt>{item.label}</dt>
            <dd className={`is-${item.tone}`}>{item.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
