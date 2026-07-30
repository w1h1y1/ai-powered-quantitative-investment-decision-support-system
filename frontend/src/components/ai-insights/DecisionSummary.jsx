import { getDisplayedInsightSummary } from '../../utils/aiInsightActions'

export default function DecisionSummary({ insight }) {
  return (
    <section className="ai-insights-card ai-insights-summary-card" aria-labelledby="ai-insights-summary-title">
      <div className="ai-insights-card-header">
        <div>
          <p>Natural language rationale</p>
          <h2 id="ai-insights-summary-title">Rule-Based Decision Summary</h2>
        </div>
      </div>
      <p>{getDisplayedInsightSummary(insight)}</p>
    </section>
  )
}
