import { useEffect, useMemo, useState } from 'react'
import { portfolioApi } from '../../services/portfolioApi'
import { formatCurrency } from './portfolioMath'

const EMPTY_VALUE = '\u2014'

const dateFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
})

const fundingTypeLabels = {
  INITIAL_DEPOSIT: 'Initial Deposit',
  INITIAL: 'Initial Deposit',
  DEPOSIT: 'Deposit',
  WITHDRAWAL: 'Withdrawal',
}

function formatFundingDate(value) {
  if (!value) return EMPTY_VALUE
  const parsedDate = new Date(value)
  if (Number.isNaN(parsedDate.getTime())) return EMPTY_VALUE
  return dateFormatter.format(parsedDate)
}

function formatFundingAmount(flow) {
  const amount = Number(flow.amount)
  if (!Number.isFinite(amount)) return EMPTY_VALUE
  const sign = flow.flow_type === 'WITHDRAWAL' ? '-' : '+'
  return `${sign}${formatCurrency(Math.abs(amount))}`
}

function getLocalDateInputValue() {
  const today = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`
}

export default function FundingPanel({ onRefresh, remainingLiquidity }) {
  const [history, setHistory] = useState([])
  const [isHistoryLoading, setIsHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState('')
  const [flowType, setFlowType] = useState('DEPOSIT')
  const [amount, setAmount] = useState('')
  const [transactionDate, setTransactionDate] = useState(getLocalDateInputValue)
  const [note, setNote] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [actionError, setActionError] = useState('')
  const [notice, setNotice] = useState('')

  const loadHistory = async () => {
    setIsHistoryLoading(true)
    setHistoryError('')
    try {
      const response = await portfolioApi.funding()
      setHistory(Array.isArray(response?.funding_transactions)
        ? response.funding_transactions
        : [])
    } catch (error) {
      setHistory([])
      setHistoryError(error?.message || 'Unable to load Funding History.')
    } finally {
      setIsHistoryLoading(false)
    }
  }

  useEffect(() => {
    loadHistory()
  }, [])

  const canInitialDeposit = useMemo(() => {
    const hasInitialDeposit = history.some(
      (flow) => flow.flow_type === 'INITIAL' && Number(flow.amount) > 0,
    )
    const hasLaterFlow = history.some((flow) => flow.flow_type !== 'INITIAL')
    return !hasInitialDeposit && !hasLaterFlow
  }, [history])

  useEffect(() => {
    if (!canInitialDeposit && flowType === 'INITIAL_DEPOSIT') {
      setFlowType('DEPOSIT')
    }
  }, [canInitialDeposit, flowType])

  const canSubmit = amount !== ''
    && Number.isFinite(Number(amount))
    && Number(amount) > 0
    && transactionDate
    && !isSubmitting

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!canSubmit) return

    setActionError('')
    setNotice('')
    setIsSubmitting(true)
    try {
      await portfolioApi.createFunding({
        flow_type: flowType,
        amount,
        transaction_date: transactionDate,
        note: note.trim(),
      })
      setAmount('')
      setNote('')
      setTransactionDate(getLocalDateInputValue())
      setNotice(`${fundingTypeLabels[flowType] ?? 'Funding'} recorded.`)
      await Promise.all([
        loadHistory(),
        onRefresh?.(),
      ])
    } catch (error) {
      setActionError(error?.message || 'Unable to record funding.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const flowOptions = [
    ...(canInitialDeposit ? [['INITIAL_DEPOSIT', 'Initial Deposit']] : []),
    ['DEPOSIT', 'Deposit'],
    ['WITHDRAWAL', 'Withdrawal'],
  ]

  return (
    <section className="portfolio-card portfolio-funding-card" aria-labelledby="funding-title">
      <div className="portfolio-card-header">
        <div>
          <p>Cash management</p>
          <h2 id="funding-title">Funding</h2>
          <span className="portfolio-performance-description">
            Record manual external cash flows. Funding is separate from investment P/L.
          </span>
        </div>
        <div className="portfolio-funding-balance">
          <span>Available Cash</span>
          <strong>{formatCurrency(Number(remainingLiquidity) || 0)}</strong>
        </div>
      </div>

      <form className="portfolio-funding-form" onSubmit={handleSubmit}>
        <label>
          <span>Type</span>
          <select value={flowType} onChange={(event) => setFlowType(event.target.value)}>
            {flowOptions.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Amount</span>
          <input
            min="0.01"
            onChange={(event) => setAmount(event.target.value)}
            placeholder="0.00"
            step="0.01"
            type="number"
            value={amount}
          />
        </label>
        <label>
          <span>Date</span>
          <input
            onChange={(event) => setTransactionDate(event.target.value)}
            type="date"
            value={transactionDate}
          />
        </label>
        <label className="portfolio-funding-note">
          <span>Note</span>
          <input
            maxLength="255"
            onChange={(event) => setNote(event.target.value)}
            placeholder="Optional note"
            type="text"
            value={note}
          />
        </label>
        <button disabled={!canSubmit} type="submit">
          {isSubmitting ? 'Saving...' : 'Record Funding'}
        </button>
      </form>

      {notice && <p className="portfolio-state-notice" role="status">{notice}</p>}
      {actionError && <p className="portfolio-state-error" role="alert">{actionError}</p>}

      <div className={`portfolio-funding-results${isHistoryLoading ? ' is-loading' : ''}`}>
        {isHistoryLoading && !history.length && (
          <p className="portfolio-transactions-notice" role="status">Loading funding history...</p>
        )}
        {!isHistoryLoading && historyError && (
          <p className="portfolio-transactions-notice is-error" role="alert">{historyError}</p>
        )}
        {!isHistoryLoading && !historyError && !history.length && (
          <p className="portfolio-transactions-notice" role="status">
            No funding history yet. Record your initial deposit to establish available cash.
          </p>
        )}

        {history.length > 0 && (
          <div className="portfolio-transactions-table-wrap">
            <table className="portfolio-transactions-table">
              <caption className="sr-only">Funding history</caption>
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Type</th>
                  <th scope="col">Amount</th>
                  <th scope="col">Note</th>
                </tr>
              </thead>
              <tbody>
                {history.map((flow) => (
                  <tr key={flow.id}>
                    <td data-label="Date">{formatFundingDate(flow.effective_date)}</td>
                    <td data-label="Type">{fundingTypeLabels[flow.flow_type] || flow.flow_type}</td>
                    <td data-label="Amount">{formatFundingAmount(flow)}</td>
                    <td data-label="Note"><span>{flow.note || EMPTY_VALUE}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}
