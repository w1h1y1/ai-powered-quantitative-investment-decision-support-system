export const suggestedActionExplanations = {
  'Hold and Monitor': 'Maintain the current position and wait for clearer confirmation before increasing exposure.',
  'Wait Before Entering': 'Delay a new entry until the trend, volatility, or forecast confidence becomes clearer.',
  'Avoid Increasing Exposure': 'Keep the current allocation unchanged while portfolio concentration remains elevated.',
  'Consider a Gradual Entry': 'Use staged position sizing and confirm that the aligned signals remain intact before increasing exposure.',
  'Consider Reducing Exposure': 'Review the current position size and consider reducing exposure if elevated risk or weak forecast evidence persists.',
  'Monitor Closely': 'Continue monitoring the asset and wait for a clearer directional setup before changing exposure.',
}

function getPortfolioMetric(insight, label) {
  return insight.portfolioContext?.metrics?.find((metric) => metric.label === label)?.value
}

function parseMetricNumber(value) {
  const parsedValue = Number(String(value ?? '').replace(/[^0-9.-]/g, ''))
  return Number.isFinite(parsedValue) ? parsedValue : null
}

export function getDisplayedSuggestedAction(insight) {
  const action = insight.suggestedAction

  if (action === 'Consider Buying') return 'Consider a Gradual Entry'
  if (action === 'Reduce Exposure') return 'Consider Reducing Exposure'
  if (action === 'Hold') return 'Hold and Monitor'
  if (action !== 'Wait for Confirmation') return action

  const position = parseMetricNumber(getPortfolioMetric(insight, 'Current Position'))
  const portfolioWeight = parseMetricNumber(getPortfolioMetric(insight, 'Portfolio Weight'))
  if (position === null) return 'Monitor Closely'
  if (position <= 0) return 'Wait Before Entering'
  if (portfolioWeight !== null && portfolioWeight >= 30) return 'Avoid Increasing Exposure'
  return 'Hold and Monitor'
}

export function getDisplayedActionExplanation(insight) {
  return insight.suggestedActionExplanation
    ?? suggestedActionExplanations[getDisplayedSuggestedAction(insight)]
}

export function getDisplayedInsightSummary(insight) {
  const displayedAction = getDisplayedSuggestedAction(insight)
  const explanation = getDisplayedActionExplanation(insight)
  const savedClosing = `${insight.suggestedAction} is framed as decision support, not an instruction to place a trade.`
  const displayedClosing = `Suggested action: ${displayedAction}. ${explanation} This is decision support, not an instruction to place a trade.`
  const selectedModelPhrase = insight.predictionContext?.selectedModel
    ? `${insight.predictionContext.selectedModel} demo prediction`
    : null

  let summary = insight.summary
  if (selectedModelPhrase) summary = summary.replace(selectedModelPhrase, 'demo forecast')

  return summary
    .replace('model agreement', 'forecast consistency')
    .replace(savedClosing, displayedClosing)
}
