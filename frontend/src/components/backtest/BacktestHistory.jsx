import { useEffect, useRef, useState } from 'react'
import { formatSignedPercentage } from '../portfolio/portfolioMath'

const dateFormatter = new Intl.DateTimeFormat('en-US', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

const runDateFormatter = new Intl.DateTimeFormat('en-US', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

function formatDate(value) {
  return dateFormatter.format(new Date(`${value}T00:00:00Z`))
}

export default function BacktestHistory({ history, onReopen, onDelete }) {
  const [pendingDelete, setPendingDelete] = useState(null)
  const cancelButtonRef = useRef(null)
  const deleteDialogRef = useRef(null)
  const deleteTriggerRef = useRef(null)

  useEffect(() => {
    if (!pendingDelete) return undefined

    const trigger = deleteTriggerRef.current
    const focusFrame = window.requestAnimationFrame(() => cancelButtonRef.current?.focus())
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setPendingDelete(null)
        return
      }

      if (event.key !== 'Tab') return
      const controls = [...(deleteDialogRef.current?.querySelectorAll('button') ?? [])]
      if (!controls.length) return

      const firstControl = controls[0]
      const lastControl = controls.at(-1)
      if (!deleteDialogRef.current?.contains(document.activeElement)) {
        event.preventDefault()
        firstControl.focus()
      } else if (event.shiftKey && document.activeElement === firstControl) {
        event.preventDefault()
        lastControl.focus()
      } else if (!event.shiftKey && document.activeElement === lastControl) {
        event.preventDefault()
        firstControl.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.removeEventListener('keydown', handleKeyDown)
      if (trigger?.isConnected) window.requestAnimationFrame(() => trigger.focus())
    }
  }, [pendingDelete])

  const requestDelete = (result, event) => {
    deleteTriggerRef.current = event.currentTarget
    setPendingDelete(result)
  }

  const confirmDelete = () => {
    if (!pendingDelete) return
    const resultId = pendingDelete.id
    onDelete(resultId)
    setPendingDelete(null)
  }

  return (
    <section className="backtest-card backtest-history-card" aria-labelledby="backtest-history-title">
      <div className="backtest-card-header">
        <div>
          <p>Saved simulations</p>
          <h2 id="backtest-history-title">Backtest History</h2>
          <span>Reopen or remove the latest completed real historical-data backtests saved in this browser.</span>
        </div>
        <strong className="backtest-record-count">{history.length} saved</strong>
      </div>

      {history.length ? (
        <div className="backtest-table-wrap">
          <table className="backtest-history-table">
            <caption className="sr-only">Saved backtest history</caption>
            <thead>
              <tr>
                <th scope="col">Asset</th>
                <th scope="col">Strategy</th>
                <th scope="col">Date Range</th>
                <th scope="col">Total Return</th>
                <th scope="col">Run Date</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {history.map((result) => (
                <tr key={result.id}>
                  <td data-label="Asset">
                    <span className="backtest-history-asset">
                      <strong>{result.asset.symbol}</strong>
                      <small>{result.asset.type}</small>
                    </span>
                  </td>
                  <td data-label="Strategy">{result.strategy.label}</td>
                  <td data-label="Date Range">{formatDate(result.config.startDate)} - {formatDate(result.config.endDate)}</td>
                  <td data-label="Total Return">
                    <strong className={result.metrics.totalReturn >= 0 ? 'is-positive' : 'is-negative'}>
                      {formatSignedPercentage(result.metrics.totalReturn)}
                    </strong>
                  </td>
                  <td data-label="Run Date">{runDateFormatter.format(new Date(result.runAt))}</td>
                  <td data-label="Actions">
                    <div className="backtest-history-actions">
                      <button type="button" onClick={() => onReopen(result)}>Reopen</button>
                      <button
                        className="is-delete"
                        type="button"
                        aria-haspopup="dialog"
                        onClick={(event) => requestDelete(result, event)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="backtest-history-empty">
          <strong>No saved backtests yet.</strong>
          <span>Completed real backtests will appear here and remain available after refresh.</span>
        </div>
      )}

      {pendingDelete && (
        <div
          className="backtest-confirm-overlay"
          onClick={(event) => {
            if (event.target === event.currentTarget) setPendingDelete(null)
          }}
        >
          <div
            className="backtest-confirm-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="backtest-delete-title"
            aria-describedby="backtest-delete-description"
            ref={deleteDialogRef}
          >
            <span className="backtest-confirm-eyebrow">Delete saved backtest</span>
            <h2 id="backtest-delete-title">
              Delete {pendingDelete.asset.symbol} {pendingDelete.strategy.label}?
            </h2>
            <p id="backtest-delete-description">
              This removes the saved result from Backtest History. This action cannot be undone.
            </p>
            <div className="backtest-confirm-actions">
              <button type="button" ref={cancelButtonRef} onClick={() => setPendingDelete(null)}>Cancel</button>
              <button className="is-confirm-delete" type="button" onClick={confirmDelete}>Delete</button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
