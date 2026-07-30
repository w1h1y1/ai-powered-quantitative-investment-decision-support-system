function createAllocationGradient(allocations) {
  let start = 0

  const stops = allocations.map((allocation) => {
    const end = start + allocation.value
    const stop = `${allocation.color} ${start}% ${end}%`
    start = end
    return stop
  })

  return `conic-gradient(${stops.join(', ')})`
}

export default function PortfolioSummary({ portfolio }) {
  const allocationGradient = createAllocationGradient(portfolio.allocations)

  return (
    <section className="dashboard-panel portfolio-panel" aria-labelledby="portfolio-title">
      <div className="panel-header">
        <div>
          <p>Account overview</p>
          <h2 id="portfolio-title">Portfolio Summary</h2>
        </div>
        <button className="panel-action" type="button">Details</button>
      </div>

      <div className="portfolio-value">
        <span>Total Account Value</span>
        <strong>{portfolio.totalAccountValue}</strong>
        <p><span>{portfolio.dayChange}</span> {portfolio.dayChangeValue}</p>
      </div>

      <p className="dashboard-allocation-note">Based on invested assets</p>
      <div className="allocation-layout">
        <div className="allocation-chart" style={{ '--allocation-chart': allocationGradient }} aria-label="Invested asset allocation chart">
          <div>
            <strong>100%</strong>
            <span>Holdings</span>
          </div>
        </div>
        <ul className="allocation-legend">
          {portfolio.allocations.map((allocation) => (
            <li key={allocation.label}>
              <span className="allocation-color" style={{ background: allocation.color }} />
              <span>{allocation.label}</span>
              <strong>{allocation.value}%</strong>
            </li>
          ))}
        </ul>
      </div>

      <div className="portfolio-gain">
        <span>Total gain</span>
        <div><strong>{portfolio.totalGain}</strong><span>{portfolio.totalGainPercent}</span></div>
      </div>
    </section>
  )
}
