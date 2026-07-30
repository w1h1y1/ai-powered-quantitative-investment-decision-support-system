import { useRef, useState } from 'react'
import DeleteInsightDialog from './DeleteInsightDialog'
import { getDisplayedSuggestedAction } from '../../utils/aiInsightActions'

const generatedDateFormatter = new Intl.DateTimeFormat('en-US', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

export default function InsightHistory({ history, currentInsightId, onReopen, onDelete }) {
  const [pendingDelete, setPendingDelete] = useState(null)
  const deleteTriggerRef = useRef(null)

  const requestDelete = (insight, event) => {
    deleteTriggerRef.current = event.currentTarget
    setPendingDelete(insight)
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
    <section className="ai-insights-card ai-insights-history-card" aria-labelledby="ai-insights-history-title">
      <div className="ai-insights-card-header">
        <div>
          <p>Saved analysis</p>
          <h2 id="ai-insights-history-title">Analysis History</h2>
          <span>Reopen or delete locally saved mock insights.</span>
        </div>
        <strong className="ai-insights-record-count">{history.length} saved</strong>
      </div>

      {history.length ? (
        <div className="ai-insights-table-wrap">
          <table className="ai-insights-history-table">
            <caption className="sr-only">Saved rule-based insight history</caption>
            <thead>
              <tr>
                <th scope="col">Asset</th>
                <th scope="col">Suggested Action</th>
                <th scope="col">Confidence</th>
                <th scope="col">Risk Level</th>
                <th scope="col">Horizon</th>
                <th scope="col">Generated Date</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {history.map((insight) => {
                const isCurrent = insight.id === currentInsightId

                return (
                  <tr key={insight.id} className={isCurrent ? 'is-current' : undefined}>
                    <td data-label="Asset">
                      <span className="ai-insights-history-asset">
                        <strong>{insight.asset.symbol}</strong>
                        <small>{insight.asset.type}</small>
                      </span>
                    </td>
                    <td data-label="Suggested Action">{getDisplayedSuggestedAction(insight)}</td>
                    <td data-label="Confidence">{insight.confidence}</td>
                    <td data-label="Risk Level">{insight.riskLevel}</td>
                    <td data-label="Horizon">{insight.configuration.horizonLabel}</td>
                    <td data-label="Generated Date">{generatedDateFormatter.format(new Date(insight.generatedAt))}</td>
                    <td data-label="Actions">
                      <div className="ai-insights-history-actions">
                        <button type="button" disabled={isCurrent} onClick={() => onReopen(insight)}>
                          Open
                        </button>
                        <button
                          type="button"
                          className="is-delete"
                          aria-haspopup="dialog"
                          onClick={(event) => requestDelete(insight, event)}
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
        <div className="ai-insights-history-empty">
          <strong>No saved insights yet.</strong>
          <span>Generated insights will remain available after refresh.</span>
        </div>
      )}

      {pendingDelete && (
        <DeleteInsightDialog
          insight={pendingDelete}
          onCancel={cancelDelete}
          onConfirm={confirmDelete}
        />
      )}
    </section>
  )
}
