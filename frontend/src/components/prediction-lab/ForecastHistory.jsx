import { useRef, useState } from 'react'
import DeleteForecastDialog from './DeleteForecastDialog'

const generatedDateFormatter = new Intl.DateTimeFormat('en-US', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

function formatSignedPercent(value) {
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}

export default function ForecastHistory({ history, currentForecastId, onOpen, onDelete }) {
  const [pendingDelete, setPendingDelete] = useState(null)
  const deleteTriggerRef = useRef(null)

  const requestDelete = (forecast, event) => {
    deleteTriggerRef.current = event.currentTarget
    setPendingDelete(forecast)
  }

  const cancelDelete = () => {
    setPendingDelete(null)
    const trigger = deleteTriggerRef.current
    if (trigger?.isConnected) window.requestAnimationFrame(() => trigger.focus())
  }

  const confirmDelete = () => {
    if (!pendingDelete) return
    onDelete(pendingDelete.id)
    setPendingDelete(null)
  }

  return (
    <section className="prediction-card prediction-history-card" aria-labelledby="prediction-history-title">
      <div className="prediction-card-header">
        <div>
          <p>Saved forecasts</p>
          <h2 id="prediction-history-title">Forecast History</h2>
          <span>Open or delete deterministic mock forecasts stored in this browser.</span>
        </div>
        <strong className="prediction-record-count">{history.length} saved</strong>
      </div>

      {history.length ? (
        <div className="prediction-history-wrap">
          <table className="prediction-history-table">
            <caption className="sr-only">Saved rule-based forecast history</caption>
            <thead>
              <tr>
                <th scope="col">Asset</th>
                <th scope="col">Horizon</th>
                <th scope="col">Direction</th>
                <th scope="col">Probability</th>
                <th scope="col">Expected Return</th>
                <th scope="col">Generated Date</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {history.map((forecast) => {
                const isCurrent = forecast.id === currentForecastId
                return (
                  <tr className={isCurrent ? 'is-current' : undefined} key={forecast.id}>
                    <td data-label="Asset">
                      <span className="prediction-history-asset">
                        <strong>{forecast.asset.symbol}</strong>
                        <small>{forecast.asset.type}</small>
                      </span>
                    </td>
                    <td data-label="Horizon">{forecast.configuration.horizonLabel}</td>
                    <td data-label="Direction">{forecast.predictedDirection}</td>
                    <td data-label="Probability">{forecast.probabilityIncrease}%</td>
                    <td data-label="Expected Return">{formatSignedPercent(forecast.expectedReturn)}</td>
                    <td data-label="Generated Date">{generatedDateFormatter.format(new Date(forecast.generatedAt))}</td>
                    <td data-label="Actions">
                      <div className="prediction-history-actions">
                        <button type="button" disabled={isCurrent} onClick={() => onOpen(forecast)}>Open</button>
                        <button
                          type="button"
                          className="is-delete"
                          aria-haspopup="dialog"
                          onClick={(event) => requestDelete(forecast, event)}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="prediction-history-empty">
          <strong>No saved forecasts yet.</strong>
          <span>Generated forecasts will remain available after refresh.</span>
        </div>
      )}

      {pendingDelete && (
        <DeleteForecastDialog forecast={pendingDelete} onCancel={cancelDelete} onConfirm={confirmDelete} />
      )}
    </section>
  )
}
