const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const quantityFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 0,
  maximumFractionDigits: 4,
})

const positionColors = {
  AAPL: '#6877f5',
  MSFT: '#2bbf8a',
  SPY: '#f3a847',
  NVDA: '#ef6a78',
  AMZN: '#4f9ee8',
  GOOGL: '#9b6de3',
  QQQ: '#41b6c4',
  TSLA: '#41b6c4',
  META: '#e58a50',
}

export function getPositionColor(symbol) {
  return positionColors[symbol] ?? '#7d8ca7'
}

export function formatCurrency(value) {
  return currencyFormatter.format(Number.isFinite(value) ? value : 0)
}

export function formatSignedCurrency(value) {
  const safeValue = Number.isFinite(value) ? value : 0
  if (Math.abs(safeValue) < 0.005) return formatCurrency(0)
  return `${safeValue > 0 ? '+' : '-'}${formatCurrency(Math.abs(safeValue))}`
}

export function formatPercentage(value) {
  const safeValue = Number.isFinite(value) ? value : 0
  return `${safeValue.toFixed(2)}%`
}

export function formatSignedPercentage(value) {
  const safeValue = Number.isFinite(value) ? value : 0
  if (Math.abs(safeValue) < 0.005) return '0.00%'
  return `${safeValue > 0 ? '+' : '-'}${Math.abs(safeValue).toFixed(2)}%`
}

export function formatQuantity(value) {
  return quantityFormatter.format(Number.isFinite(value) ? value : 0)
}

export function formatCompactCurrency(value) {
  const safeValue = Number.isFinite(value) ? value : 0
  if (Math.abs(safeValue) >= 1000000) return `$${(safeValue / 1000000).toFixed(1)}M`
  if (Math.abs(safeValue) >= 1000) return `$${(safeValue / 1000).toFixed(1)}K`
  return formatCurrency(safeValue)
}
