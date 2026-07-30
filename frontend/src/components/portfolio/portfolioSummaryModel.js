import {
  formatCurrency,
  formatPercentage,
  formatSignedCurrency,
  getPositionColor,
} from './portfolioMath.js'

const PLACEHOLDER = '\u2014'

export const SUMMARY_GRID_COLUMNS = Object.freeze({
  desktop: 3,
  tablet: 2,
  mobile: 1,
})

export const SUMMARY_CARD_LABELS = Object.freeze([
  'Total Assets',
  'Holdings Market Value',
  'Remaining Liquidity',
  'Total Cost',
  'Unrealized Profit / Loss',
  'Return Percentage',
])

export function parseDecimal(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

export function parseCount(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0
}

export function formatSecurityType(value) {
  if (value === 'STOCK') return 'Stock'
  if (value === 'ETF') return 'ETF'
  return value || 'Security'
}

function getTone(value) {
  if (value > 0) return 'is-positive'
  if (value < 0) return 'is-negative'
  return 'is-neutral'
}

function formatHoldingsDetail(count) {
  const safeCount = parseCount(count)
  if (safeCount === 0) return 'No positions - Demo prices'
  if (safeCount === 1) return '1 position - Demo prices'
  return `${safeCount} positions - Demo prices`
}

export function normalizeSecurity(security) {
  if (!security) return null

  return {
    id: security.id,
    symbol: security.symbol,
    name: security.name,
    type: formatSecurityType(security.asset_type),
    assetType: security.asset_type,
    currency: security.currency,
    isActive: security.is_active !== false,
  }
}

function normalizeSummaryAllocation(allocation) {
  if (!allocation) return null
  const quantity = parseDecimal(allocation.quantity)
  const averageCost = parseDecimal(allocation.average_price)
  const currentPrice = parseDecimal(allocation.current_price)
  const marketValue = parseDecimal(allocation.market_value)
  const costBasis = parseDecimal(allocation.cost)
  const totalGainLoss = parseDecimal(allocation.unrealized_profit_loss)
  const totalGainLossPercent = parseDecimal(allocation.unrealized_return_percent)
  const positionWeight = parseDecimal(allocation.allocation_percent)

  return {
    id: allocation.holding_id,
    securityId: allocation.security_id,
    symbol: allocation.symbol,
    asset: allocation.name || allocation.symbol,
    type: formatSecurityType(allocation.security_type),
    currency: allocation.currency || 'USD',
    quantity,
    averageCost,
    currentPrice,
    marketValue,
    costBasis,
    totalGainLoss,
    totalGainLossPercent,
    positionWeight,
    todayGainLoss: 0,
    dailyChangePercent: 0,
    currentPriceSource: allocation.current_price_source,
  }
}

export function normalizePortfolioSummary(summary) {
  if (!summary?.portfolio_id) return null

  const holdings = Array.isArray(summary.allocations)
    ? summary.allocations.map(normalizeSummaryAllocation).filter(Boolean)
    : []
  const holdingsValue = parseDecimal(summary.holdings_market_value)

  return {
    portfolioId: summary.portfolio_id,
    portfolioName: summary.portfolio_name || 'My Portfolio',
    portfolioCreatedAt: summary.portfolio_created_at,
    baseCurrency: summary.base_currency || 'USD',
    priceSource: summary.price_source || 'DEMO_STATIC',
    holdings,
    allocation: holdings.map((holding) => ({
      key: holding.id ?? holding.symbol,
      symbol: holding.symbol,
      asset: holding.asset,
      amount: holding.marketValue,
      percentage: holding.positionWeight,
      color: getPositionColor(holding.symbol),
    })),
    summary: {
      holdingsCount: parseCount(summary.holdings_count),
      totalAccountValue: parseDecimal(summary.total_asset_value),
      holdingsValue,
      availableFunds: parseDecimal(summary.remaining_liquidity),
      costBasis: parseDecimal(summary.total_cost),
      totalGainLoss: parseDecimal(summary.unrealized_profit_loss),
      totalGainLossPercent: parseDecimal(summary.unrealized_return_percent),
    },
  }
}

export function buildPortfolioSummaryCards(summary) {
  const hasSummary = Boolean(summary)
  const safeSummary = summary ?? {}
  const totalGainLoss = parseDecimal(safeSummary.totalGainLoss)

  return [
    {
      label: 'Total Assets',
      value: hasSummary ? formatCurrency(parseDecimal(safeSummary.totalAccountValue)) : PLACEHOLDER,
      detail: 'Holdings market value plus remaining liquidity',
    },
    {
      label: 'Holdings Market Value',
      value: hasSummary ? formatCurrency(parseDecimal(safeSummary.holdingsValue)) : PLACEHOLDER,
      detail: formatHoldingsDetail(safeSummary.holdingsCount),
    },
    {
      label: 'Remaining Liquidity',
      value: hasSummary ? formatCurrency(parseDecimal(safeSummary.availableFunds)) : PLACEHOLDER,
      detail: 'Remaining funds available for investment',
    },
    {
      label: 'Total Cost',
      value: hasSummary ? formatCurrency(parseDecimal(safeSummary.costBasis)) : PLACEHOLDER,
      detail: 'Quantity multiplied by average price',
    },
    {
      label: 'Unrealized Profit / Loss',
      value: hasSummary ? formatSignedCurrency(totalGainLoss) : PLACEHOLDER,
      detail: 'Market value minus total cost',
      tone: hasSummary ? getTone(totalGainLoss) : undefined,
    },
    {
      label: 'Return Percentage',
      value: hasSummary ? formatPercentage(parseDecimal(safeSummary.totalGainLossPercent)) : PLACEHOLDER,
      detail: 'Unrealized P/L divided by total cost',
      tone: hasSummary ? getTone(totalGainLoss) : undefined,
    },
  ]
}
