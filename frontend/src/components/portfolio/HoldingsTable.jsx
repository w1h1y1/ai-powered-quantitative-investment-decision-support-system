import Icon from '../Icon'
import {
  formatCurrency,
  formatPercentage,
  formatQuantity,
  formatSignedCurrency,
  formatSignedPercentage,
} from './portfolioMath'

function getTone(value) {
  if (value > 0) return 'is-positive'
  if (value < 0) return 'is-negative'
  return 'is-neutral'
}

export default function HoldingsTable({
  holdings,
  holdingsCount = 0,
  isActionPending = false,
  onBuy,
  onSell,
  onViewAnalysis,
}) {
  const safeHoldingsCount = Number.isFinite(holdingsCount) && holdingsCount > 0
    ? Math.floor(holdingsCount)
    : 0

  return (
    <section className="portfolio-card portfolio-holdings-card" aria-labelledby="portfolio-holdings-title">
      <div className="portfolio-card-header">
        <div>
          <p>Owned assets</p>
          <h2 id="portfolio-holdings-title">Holdings ({safeHoldingsCount})</h2>
          <span className="portfolio-performance-description">Rows and calculated values come from PostgreSQL Summary API. Current prices are Demo Data.</span>
        </div>
        {holdings.length > 0 && (
          <button className="portfolio-card-action" type="button" onClick={onBuy}>Buy</button>
        )}
      </div>

      {holdings.length ? (
        <div className="portfolio-table-wrap">
          <table className="portfolio-holdings-table">
            <caption className="sr-only">Current portfolio holdings and performance</caption>
            <thead>
              <tr>
                <th scope="col">Symbol</th>
                <th scope="col">Asset</th>
                <th scope="col">Type</th>
                <th scope="col">Quantity</th>
                <th scope="col">Average Cost</th>
                <th scope="col">Current Price</th>
                <th scope="col">Market Value</th>
                <th scope="col">Position Weight</th>
                <th scope="col">Today's Change</th>
                <th scope="col">Total Gain / Loss</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((holding) => (
                <tr key={holding.id ?? holding.symbol}>
                  <td data-label="Symbol"><strong className="portfolio-holding-symbol">{holding.symbol}</strong></td>
                  <td data-label="Asset">
                    <span className="portfolio-holding-name" title={holding.asset}>{holding.asset}</span>
                  </td>
                  <td data-label="Type">
                    <span className={`portfolio-asset-type is-${holding.type.toLowerCase()}`}>{holding.type}</span>
                  </td>
                  <td data-label="Quantity">{formatQuantity(holding.quantity)}</td>
                  <td data-label="Average Cost">{formatCurrency(holding.averageCost)}</td>
                  <td data-label="Current Price"><strong>{formatCurrency(holding.currentPrice)}</strong></td>
                  <td data-label="Market Value"><strong>{formatCurrency(holding.marketValue)}</strong></td>
                  <td data-label="Position Weight">{formatPercentage(holding.positionWeight)}</td>
                  <td data-label="Today's Change">
                    <span className={`portfolio-table-result ${getTone(holding.todayGainLoss)}`}>
                      <strong>{formatSignedCurrency(holding.todayGainLoss)}</strong>
                      <small>{formatSignedPercentage(holding.dailyChangePercent)}</small>
                    </span>
                  </td>
                  <td data-label="Total Gain / Loss">
                    <span className={`portfolio-table-result ${getTone(holding.totalGainLoss)}`}>
                      <strong>{formatSignedCurrency(holding.totalGainLoss)}</strong>
                      <small>{formatSignedPercentage(holding.totalGainLossPercent)}</small>
                    </span>
                  </td>
                  <td data-label="Actions">
                    <div className="portfolio-row-actions">
                      <button
                        type="button"
                        onClick={() => onViewAnalysis(holding.symbol)}
                        aria-label={`View ${holding.symbol} analysis`}
                      >
                        View Analysis
                      </button>
                      <button
                        className="is-sell"
                        disabled={isActionPending}
                        type="button"
                        onClick={() => onSell(holding)}
                        aria-label={`Sell ${holding.symbol}`}
                      >
                        Sell
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="portfolio-empty-state">
          <span className="portfolio-empty-icon" aria-hidden="true"><Icon name="portfolio" /></span>
          <h3>No holdings yet.</h3>
          <p>Record a buy transaction to start tracking this Portfolio.</p>
          <button type="button" onClick={onBuy}>Buy</button>
        </div>
      )}
    </section>
  )
}
