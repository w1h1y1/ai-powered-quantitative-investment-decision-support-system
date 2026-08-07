import { formatCurrency, formatQuantity } from '../portfolio/portfolioMath'

const dateFormatter = new Intl.DateTimeFormat('en-US', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

function formatDate(value) {
  if (!value) return '-'
  return dateFormatter.format(new Date(`${value}T00:00:00Z`))
}

function getProfitLossTone(value) {
  if (value > 0) return 'is-positive'
  if (value < 0) return 'is-negative'
  return 'is-neutral'
}

function formatReason(value) {
  return String(value || '').replaceAll('_', ' ')
}

function getSizingExplanation(trade) {
  if (trade.type !== 'BUY' || trade.riskAmount === null) return undefined
  return [
    `Equity before: ${formatCurrency(trade.equityBefore)}`,
    `Risk fraction: ${trade.riskFraction === null ? 'N/A' : `${(trade.riskFraction * 100).toFixed(2)}%`}`,
    `Risk amount: ${formatCurrency(trade.riskAmount)}`,
    `ATR: ${trade.atr}`,
    `Stop distance: ${formatCurrency(trade.stopDistance)}`,
    `Raw quantity: ${formatQuantity(trade.rawQuantity)}`,
    `Affordable quantity: ${formatQuantity(trade.affordableQuantity)}`,
    `Exposure cap quantity: ${formatQuantity(trade.exposureCappedQuantity)}`,
    `Final quantity: ${formatQuantity(trade.finalQuantity)}`,
    `Raw exposure: ${trade.rawExposure?.toFixed(2)}%`,
    `Final exposure: ${trade.finalExposure?.toFixed(2)}%`,
    `Exposure cap applied: ${trade.exposureCapApplied ? 'yes' : 'no'}`,
    `Cash cap applied: ${trade.cashCapApplied ? 'yes' : 'no'}`,
  ].join(' | ')
}

export default function TradeHistoryTable({ trades }) {
  return (
    <section className="backtest-card backtest-trades-card" aria-labelledby="backtest-trades-title">
      <div className="backtest-card-header">
        <div>
          <p>Executed layered orders</p>
          <h2 id="backtest-trades-title">Trade History</h2>
          <span>Core and Swing quantities are accounted for independently and all orders execute at next-day open.</span>
        </div>
        <strong className="backtest-record-count">{trades.length} orders</strong>
      </div>

      <div className="backtest-table-wrap">
        <table className="backtest-trades-table">
          <caption className="sr-only">Backtest layered trade history</caption>
          <thead>
            <tr>
              <th scope="col">Signal Date</th>
              <th scope="col">Execution Date</th>
              <th scope="col">Layer</th>
              <th scope="col">Action</th>
              <th scope="col">Reason</th>
              <th scope="col">Price</th>
              <th scope="col">Quantity</th>
              <th scope="col">Fee</th>
              <th scope="col">Cash After</th>
              <th scope="col">Core After</th>
              <th scope="col">Swing After</th>
              <th scope="col">Realized P/L</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <tr key={trade.id}>
                <td data-label="Signal Date">{formatDate(trade.signalDate)}</td>
                <td data-label="Execution Date">{formatDate(trade.executionDate)}</td>
                <td data-label="Layer"><span className={`backtest-layer-badge is-${trade.positionLayer.toLowerCase()}`}>{trade.positionLayer}</span></td>
                <td data-label="Action"><span className={`backtest-trade-action is-${trade.action.toLowerCase()}`}>{trade.action}</span></td>
                <td data-label="Reason">
                  <span className="backtest-trade-reason">{formatReason(trade.reason)}</span>
                  {trade.exposureCapApplied && <small className="backtest-sizing-badge">Exposure cap</small>}
                  {trade.cashCapApplied && <small className="backtest-sizing-badge">Cash cap</small>}
                </td>
                <td data-label="Price">{formatCurrency(trade.price)}</td>
                <td data-label="Quantity" title={getSizingExplanation(trade)}>{formatQuantity(trade.quantity)}</td>
                <td data-label="Fee">{formatCurrency(trade.fee)}</td>
                <td data-label="Cash After"><strong>{formatCurrency(trade.cashAfter)}</strong></td>
                <td data-label="Core After">{formatQuantity(trade.coreQuantityAfter)}</td>
                <td data-label="Swing After">{formatQuantity(trade.swingQuantityAfter)}</td>
                <td data-label="Realized P/L"><span className={`backtest-return ${getProfitLossTone(trade.realizedProfitLoss)}`}>{formatCurrency(trade.realizedProfitLoss)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
