const enumLabels = {
  high_volatility: 'High Volatility',
  sideways_range: 'Sideways Range',
  bullish_trend: 'Bullish Trend',
  bearish_trend: 'Bearish Trend',
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
