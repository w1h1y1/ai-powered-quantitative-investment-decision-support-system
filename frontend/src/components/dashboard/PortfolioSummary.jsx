import {
  formatCurrency,
  formatSignedCurrency,
  formatSignedPercentage,
} from '../portfolio/portfolioMath'

function createAllocationGradient(allocations) {
  if (!allocations.length) return 'conic-gradient(#e7ebf2 0% 100%)'

  let start = 0

  const stops = allocations.map((allocation) => {
    const end = allocation === allocations.at(-1) ? 100 : start + allocation.value
    const stop = `${allocation.color} ${start}% ${end}%`
    start = end
    return stop
  })

  return `conic-gradient(${stops.join(', ')})`
}

function buildPortfolioCardModel(portfolio) {
  const summary = portfolio?.summary
  if (!summary) return null

  const allocations = portfolio.allocation.length
    ? portfolio.allocation.map((allocation) => ({
      label: allocation.symbol,
      value: allocation.percentage,
      color: allocation.color,
    }))
    : []
  const totalGainLoss = summary.totalGainLoss
  const totalGainLossPercent = summary.totalGainLossPercent

  return {
    totalAccountValue: formatCurrency(summary.totalAccountValue),
    dayChange: formatSignedPercentage(totalGainLossPercent),
    dayChangeValue: `${formatSignedCurrency(totalGainLoss)} unrealized`,
    totalGain: formatSignedCurrency(totalGainLoss),
    totalGainPercent: formatSignedPercentage(totalGainLossPercent),
    allocations,
  }
}

function PortfolioPanelState({ children, onRetry }) {
  return (
    <div className="portfolio-value">
      {children}
      {onRetry && <button className="panel-action" type="button" onClick={onRetry}>Retry</button>}
    </div>
  )
}

export default function PortfolioSummary({ error = '', isLoading = false, onRetry, onViewDetails, portfolio }) {
  const card = buildPortfolioCardModel(portfolio)
  const allocations = card?.allocations ?? []
  const allocationGradient = createAllocationGradient(allocations)

  return (
    <section className="dashboard-panel portfolio-panel" aria-labelledby="portfolio-title">
      <div className="panel-header">
        <div>
          <p>Account overview</p>
          <h2 id="portfolio-title">Portfolio Summary</h2>
        </div>
        <button className="panel-action" type="button" onClick={onViewDetails}>Details</button>
      </div>

      {isLoading ? (
        <PortfolioPanelState>
          <span>Total Account Value</span>
          <strong>Loading...</strong>
          <p>Loading Portfolio Summary from Django.</p>
        </PortfolioPanelState>
      ) : error ? (
        <PortfolioPanelState onRetry={onRetry}>
          <span>Total Account Value</span>
          <strong>Unavailable</strong>
          <p>{error}</p>
        </PortfolioPanelState>
      ) : !card ? (
        <PortfolioPanelState>
          <span>Total Account Value</span>
          <strong>$0.00</strong>
          <p>No Portfolio Summary available.</p>
        </PortfolioPanelState>
      ) : (
        <>
          <div className="portfolio-value">
            <span>Total Account Value</span>
            <strong>{card.totalAccountValue}</strong>
            <p><span>{card.dayChange}</span> {card.dayChangeValue}</p>
          </div>

          <p className="dashboard-allocation-note">Based on invested assets</p>
          <div className="allocation-layout">
            <div className="allocation-chart" style={{ '--allocation-chart': allocationGradient }} aria-label="Invested asset allocation chart">
              <div>
                <strong>{allocations.length ? '100%' : '0%'}</strong>
                <span>Holdings</span>
              </div>
            </div>
            <ul className="allocation-legend">
              {allocations.length ? allocations.map((allocation) => (
                <li key={allocation.label}>
                  <span className="allocation-color" style={{ background: allocation.color }} />
                  <span>{allocation.label}</span>
                  <strong>{allocation.value}%</strong>
                </li>
              )) : (
                <li>
                  <span className="allocation-color" style={{ background: '#e7ebf2' }} />
                  <span>No holdings</span>
                  <strong>0%</strong>
                </li>
              )}
            </ul>
          </div>

          <div className="portfolio-gain">
            <span>Total gain</span>
            <div><strong>{card.totalGain}</strong><span>{card.totalGainPercent}</span></div>
          </div>
        </>
      )}
    </section>
  )
}
