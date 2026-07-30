import { aiInsightNavigationActions } from '../../data/aiInsightsMockData'
import { getDisplayedActionExplanation } from '../../utils/aiInsightActions'
import Icon from '../Icon'

export default function RecommendedNextSteps({ insight, steps, onNavigate }) {
  const actionExplanation = getDisplayedActionExplanation(insight)
  const displaySteps = !actionExplanation || steps[0] === actionExplanation
    ? steps
    : [actionExplanation, ...steps]

  return (
    <section className="ai-insights-card ai-insights-next-card" aria-labelledby="ai-insights-next-title">
      <div className="ai-insights-card-header">
        <div>
          <p>Decision support</p>
          <h2 id="ai-insights-next-title">Recommended Next Steps</h2>
          <span>Suggested review actions only. No orders are created or transmitted.</span>
        </div>
      </div>

      <div className="ai-insights-next-layout">
        <ol className="ai-insights-next-list">
          {displaySteps.map((step) => <li key={step}>{step}</li>)}
        </ol>

        <div className="ai-insights-next-actions" aria-label="Quick navigation">
          {aiInsightNavigationActions.map((action) => (
            <button type="button" key={action.id} onClick={() => onNavigate(action.targetSection)}>
              <Icon name={action.icon} />
              <span>{action.label}</span>
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}
