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

const filterPresets = [
  ['TODAY', 'Today'],
  ['7D', '7D'],
  ['1M', '1M'],
  ['3M', '3M'],
  ['YTD', 'YTD'],
  ['Q1', 'Q1'],
  ['Q2', 'Q2'],
  ['Q3', 'Q3'],
  ['Q4', 'Q4'],
  ['CUSTOM', 'Custom'],
]

function buildPaginationSummary(pagination) {
  const count = Math.max(Number(pagination?.count) || 0, 0)
  const page = Math.max(Number(pagination?.page) || 1, 1)
  const pageSize = Math.max(Number(pagination?.pageSize) || 10, 1)
  if (!count) return 'Showing 0 transactions'
  const start = (page - 1) * pageSize + 1
  const end = Math.min(page * pageSize, count)
  return `Showing ${start}\u2013${end} of ${count} transactions`
}

export default function RecentTransactions({
  actionError = '',
  error = '',
  filters,
  isLoading = false,
  isResetting = false,
  onCustomDateChange,
  onPageChange,
  onPageSizeChange,
  onPresetChange,
  onReset,
  onYearChange,
  pagination,
  transactions = [],
}) {
  const hasTransactions = transactions.length > 0
  const selectedPreset = filters?.preset || 'TODAY'
  const selectedYear = filters?.year || new Date().getFullYear()
  const page = Math.max(Number(pagination?.page) || 1, 1)
  const pageSize = Number(pagination?.pageSize) || 10
  const count = Number(pagination?.count) || 0
  const hasPreviousPage = Boolean(pagination?.previous) || page > 1
  const hasNextPage = Boolean(pagination?.next) || page * pageSize < count

  return (
    <section className="portfolio-card portfolio-transactions-card" aria-labelledby="recent-transactions-title">
      <div className="portfolio-card-header">
        <div>
          <p>Account activity</p>
          <h2 id="recent-transactions-title">Transaction History</h2>
          <span className="portfolio-performance-description">Loaded from the Django Transactions API.</span>
        </div>
        {onReset && (
          <button
            className="portfolio-card-action is-danger"
            disabled={isLoading || isResetting}
            type="button"
            onClick={onReset}
          >
            {isResetting ? 'Resetting...' : 'Reset Test Portfolio'}
          </button>
        )}
      </div>

      <div className="portfolio-transaction-filters" aria-label="Transaction history filters">
        <div className="portfolio-transaction-range-buttons" role="radiogroup" aria-label="Transaction date range">
          {filterPresets.map(([preset, label]) => (
            <button
              className={selectedPreset === preset ? 'is-active' : ''}
              key={preset}
              type="button"
              role="radio"
              aria-checked={selectedPreset === preset}
              onClick={() => onPresetChange?.(preset)}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="portfolio-transaction-year-filter">
          <span>Year</span>
          <input
            min="1900"
            max="2200"
            type="number"
            value={selectedYear}
            onChange={(event) => onYearChange?.(event.target.value)}
          />
        </label>
        {selectedPreset === 'CUSTOM' && (
          <div className="portfolio-transaction-custom-range">
            <label>
              <span>Start</span>
              <input
                type="date"
                value={filters?.customStartDate || ''}
                onChange={(event) => onCustomDateChange?.('customStartDate', event.target.value)}
              />
            </label>
            <label>
              <span>End</span>
              <input
                type="date"
                value={filters?.customEndDate || ''}
                onChange={(event) => onCustomDateChange?.('customEndDate', event.target.value)}
              />
            </label>
          </div>
        )}
      </div>

      <div className={`portfolio-transactions-results${isLoading ? ' is-loading' : ''}`}>
        {isLoading && !hasTransactions && (
          <p className="portfolio-transactions-notice" role="status">Loading transactions...</p>
        )}
        {!isLoading && error && <p className="portfolio-transactions-notice is-error" role="alert">{error}</p>}
        {!isLoading && actionError && <p className="portfolio-transactions-notice is-error" role="alert">{actionError}</p>}
        {!isLoading && !error && !hasTransactions && (
          <p className="portfolio-transactions-notice" role="status">No transactions found for the selected period.</p>
        )}

        {hasTransactions && (
          <>
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
            <div className="portfolio-transactions-pagination" aria-label="Transaction history pagination">
              <span>{buildPaginationSummary(pagination)}</span>
              <div>
                <label>
                  <span>Rows</span>
                  <select value={pageSize} onChange={(event) => onPageSizeChange?.(event.target.value)}>
                    {[10, 25, 50].map((option) => (
                      <option key={option} value={option}>{option}</option>
                    ))}
                  </select>
                </label>
                <button
                  disabled={!hasPreviousPage || isLoading}
                  type="button"
                  onClick={() => onPageChange?.(page - 1)}
                >
                  Previous
                </button>
                <button
                  disabled={!hasNextPage || isLoading}
                  type="button"
                  onClick={() => onPageChange?.(page + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}

        {isLoading && hasTransactions && (
          <div className="portfolio-transactions-loading-overlay" role="status">
            Refreshing transactions...
          </div>
        )}
      </div>
    </section>
  )
}
