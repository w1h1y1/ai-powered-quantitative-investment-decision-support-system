import Icon from '../Icon'
import {
  getDisplayedActionExplanation,
  getDisplayedSuggestedAction,
} from '../../utils/aiInsightActions'

const overviewItems = [
  { key: 'suggestedAction', label: 'Suggested Action', icon: 'target' },
  { key: 'confidence', label: 'Overall Confidence', icon: 'check' },
  { key: 'riskLevel', label: 'Risk Level', icon: 'shield' },
  { key: 'marketBias', label: 'Market Bias', icon: 'trend' },
]

function getTone(item, value) {
  if (item.key === 'suggestedAction') {
    if (value === 'Consider a Gradual Entry' || value === 'Consider Buying') return 'positive'
    if (value === 'Consider Reducing Exposure' || value === 'Reduce Exposure') return 'negative'
    if (value === 'Avoid Increasing Exposure' || value === 'Wait Before Entering' || value === 'Wait for Confirmation') return 'warning'
    return 'neutral'
  }

  if (item.key === 'confidence') return value === 'High' ? 'positive' : value === 'Low' ? 'negative' : 'neutral'
  if (item.key === 'riskLevel') return value === 'High' ? 'negative' : value === 'Low' ? 'positive' : 'warning'
  if (item.key === 'marketBias') return value.includes('Bullish') ? 'positive' : value.includes('Bearish') ? 'negative' : 'neutral'
  return 'neutral'
}

function getValue(insight, key) {
  if (key === 'suggestedAction') return getDisplayedSuggestedAction(insight)
  if (key === 'confidence') return insight.confidence
  if (key === 'riskLevel') return insight.riskLevel
  return insight.marketBias
}

export default function DecisionOverview({ insight }) {
  return (
    <section className="ai-insights-overview" aria-labelledby="ai-insights-overview-title">
      <div className="ai-insights-result-heading">
        <p>Decision overview</p>
        <h2 id="ai-insights-overview-title">Decision Overview</h2>
      </div>

      <div className="ai-insights-overview-grid">
        {overviewItems.map((item) => {
          const value = getValue(insight, item.key)
          const tone = getTone(item, value)
          const actionExplanation = item.key === 'suggestedAction'
            ? getDisplayedActionExplanation(insight)
            : null

          return (
            <article className={`ai-insights-overview-tile is-${tone}`} key={item.key}>
              <span className="ai-insights-overview-icon" aria-hidden="true">
                <Icon name={item.icon} />
              </span>
              <div>
                <span>{item.label}</span>
                <strong>{value}</strong>
                {actionExplanation && <p className="ai-insights-action-explanation">{actionExplanation}</p>}
              </div>
            </article>
          )
        })}
      </div>
    </section>
  )
}
