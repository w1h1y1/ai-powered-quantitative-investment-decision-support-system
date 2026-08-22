const enumLabels = {
  high_volatility: 'High Volatility',
  sideways_range: 'Sideways Range',
  bullish_trend: 'Bullish Trend',
  bearish_trend: 'Bearish Trend',
  trend_following: 'Trend Following',
  mean_reversion: 'Mean Reversion',
  risk_off: 'Risk Off',
  no_strategy: 'No Suitable Strategy',
  not_allowed: 'Not Allowed',
  insufficient_evidence: 'Insufficient Evidence',
  llm_synthesis: 'LLM Synthesis',
  quantitative_fallback: 'Quantitative Fallback',
  llm_invalid_json: 'LLM Invalid JSON',
  llm_schema_validation_failed: 'LLM Schema Validation Failed',
}

export function formatAnalysisEnumLabel(value) {
  return enumLabels[value] ?? String(value ?? '')
}

export function formatRatioAsPercent(value) {
  if (value === null || value === undefined || value === '') return 'N/A'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 'N/A'
  return `${(parsed * 100).toFixed(2)}%`
}

export function formatPercentValue(value) {
  if (value === null || value === undefined || value === '') return 'N/A'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 'N/A'
  return `${parsed.toFixed(2)}%`
}

export function formatGeneratedAt(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}
