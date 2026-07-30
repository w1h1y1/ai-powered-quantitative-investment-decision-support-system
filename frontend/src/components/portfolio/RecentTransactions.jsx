import { formatCurrency, formatQuantity } from './portfolioMath'

const EMPTY_VALUE = '\u2014'

const dateTimeFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

function formatTransactionDate(value) {
  if (!value) return EMPTY_VALUE
  const parsedDate = new Date(value)
  if (Number.isNaN(parsedDate.getTime())) return EMPTY_VALUE
  return dateTimeFormatter.format(parsedDate)
}

function formatTransactionType(value) {
  if (value === 'BUY') return 'Buy'
  if (value === 'SELL') return 'Sell'
  if (value === 'DIVIDEND') return 'Dividend'
  return value || EMPTY_VALUE
}

function formatOptionalQuantity(value) {
  if (value === null || value === undefined || value === '') return EMPTY_VALUE
  const parsed = Number(value)
  return Number.isFinite(parsed) ? formatQuantity(parsed) : EMPTY_VALUE
}

function formatOptionalCurrency(value) {
  if (value === null || value === undefined || value === '') return EMPTY_VALUE
  const parsed = Number(value)
  return Number.isFinite(parsed) ? formatCurrency(parsed) : EMPTY_VALUE
}

export default function RecentTransactions({ error = '', isLoading = false, transactions = [] }) {
  const hasTransactions = transactions.length > 0

  return (
    <section className="portfolio-card portfolio-transactions-card" aria-labelledby="recent-transactions-title">
      <div className="portfolio-card-header">
        <div>
          <p>Account activity</p>
          <h2 id="recent-transactions-title">Transaction History</h2>
          <span className="portfolio-performance-description">Loaded from the Django Transactions API.</span>
        </div>
      </div>

      {isLoading && <p className="portfolio-transactions-notice" role="status">Loading transactions...</p>}
      {!isLoading && error && <p className="portfolio-transactions-notice is-error" role="alert">{error}</p>}
      {!isLoading && !error && !hasTransactions && (
        <p className="portfolio-transactions-notice" role="status">No transactions recorded yet.</p>
      )}

      {!isLoading && !error && hasTransactions && (
        <div className="portfolio-transactions-table-wrap">
          <table className="portfolio-transactions-table">
            <caption className="sr-only">Portfolio transaction history</caption>
            <thead>
              <tr>
                <th scope="col">Transaction Date</th>
                <th scope="col">Type</th>
                <th scope="col">Security</th>
                <th scope="col">Security Name</th>
                <th scope="col">Quantity</th>
                <th scope="col">Price</th>
                <th scope="col">Cash Amount</th>
                <th scope="col">Fee</th>
                <th scope="col">Notes</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((transaction) => (
                <tr key={transaction.id}>
                  <td data-label="Transaction Date">{formatTransactionDate(transaction.transaction_date)}</td>
                  <td data-label="Type">
                    <span className={`portfolio-transaction-type is-${String(transaction.transaction_type || '').toLowerCase()}`}>
                      {formatTransactionType(transaction.transaction_type)}
                    </span>
                  </td>
                  <td data-label="Security"><strong>{transaction.security?.symbol || EMPTY_VALUE}</strong></td>
                  <td data-label="Security Name"><span>{transaction.security?.name || EMPTY_VALUE}</span></td>
                  <td data-label="Quantity">{formatOptionalQuantity(transaction.quantity)}</td>
                  <td data-label="Price">{formatOptionalCurrency(transaction.price)}</td>
                  <td data-label="Cash Amount">{formatOptionalCurrency(transaction.cash_amount)}</td>
                  <td data-label="Fee">{formatOptionalCurrency(transaction.fee)}</td>
                  <td data-label="Notes"><span>{transaction.notes || EMPTY_VALUE}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
