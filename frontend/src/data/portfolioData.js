const portfolioAssetMetadata = {
  AAPL: { asset: 'Apple Inc.', type: 'Stock' },
  MSFT: { asset: 'Microsoft Corporation', type: 'Stock' },
  NVDA: { asset: 'NVIDIA Corporation', type: 'Stock' },
  AMZN: { asset: 'Amazon.com Inc.', type: 'Stock' },
  GOOGL: { asset: 'Alphabet Inc.', type: 'Stock' },
  TSLA: { asset: 'Tesla Inc.', type: 'Stock' },
  META: { asset: 'Meta Platforms Inc.', type: 'Stock' },
  SPY: { asset: 'SPDR S&P 500 ETF', type: 'ETF' },
}

function parseSignedValue(value) {
  const parsed = Number(String(value).replace(/[^0-9.-]/g, ''))
  return Number.isFinite(parsed) ? parsed : 0
}

export function createPortfolioAssetUniverse(stocks) {
  return stocks
    .filter((stock) => portfolioAssetMetadata[stock.symbol])
    .map((stock) => ({
      symbol: stock.symbol,
      asset: portfolioAssetMetadata[stock.symbol].asset,
      type: portfolioAssetMetadata[stock.symbol].type,
      currentPrice: stock.price,
      dailyChange: parseSignedValue(stock.change),
      dailyChangePercent: parseSignedValue(stock.percent),
    }))
}

export const portfolioPerformanceRanges = ['1M', '3M', '6M', '1Y']

const portfolioPerformancePatterns = {
  '1M': {
    labels: ['Jun 16', 'Jun 23', 'Jun 30', 'Jul 7', 'Jul 15'],
    totalAccountValue: [0.972, 0.978, 0.974, 0.981, 0.985, 0.982, 0.989, 0.993, 0.990, 0.996, 0.994, 1.001, 0.998, 1.004, 1.002, 1],
    costBasis: [0.98, 0.98, 0.98, 0.986, 0.986, 0.986, 0.991, 0.991, 0.991, 0.996, 0.996, 0.996, 1, 1, 1, 1],
  },
  '3M': {
    labels: ['Apr 15', 'May 8', 'Jun 1', 'Jun 24', 'Jul 15'],
    totalAccountValue: [0.928, 0.936, 0.944, 0.939, 0.951, 0.958, 0.955, 0.966, 0.972, 0.969, 0.981, 0.986, 0.982, 0.992, 0.996, 1],
    costBasis: [0.91, 0.91, 0.925, 0.925, 0.94, 0.94, 0.954, 0.954, 0.968, 0.968, 0.982, 0.982, 0.992, 0.992, 1, 1],
  },
  '6M': {
    labels: ['Jan 15', 'Mar 1', 'Apr 15', 'Jun 1', 'Jul 15'],
    totalAccountValue: [0.865, 0.878, 0.892, 0.884, 0.906, 0.918, 0.911, 0.934, 0.947, 0.941, 0.958, 0.969, 0.965, 0.981, 0.991, 1],
    costBasis: [0.82, 0.82, 0.844, 0.844, 0.868, 0.868, 0.892, 0.892, 0.916, 0.916, 0.94, 0.94, 0.966, 0.966, 0.986, 1],
  },
  '1Y': {
    labels: ['Jul 2025', 'Oct 2025', 'Jan 2026', 'Apr 2026', 'Jul 2026'],
    totalAccountValue: [0.742, 0.768, 0.751, 0.789, 0.815, 0.802, 0.846, 0.872, 0.861, 0.902, 0.921, 0.914, 0.948, 0.966, 0.987, 1],
    costBasis: [0.69, 0.69, 0.724, 0.724, 0.758, 0.758, 0.792, 0.792, 0.826, 0.826, 0.86, 0.86, 0.904, 0.904, 0.958, 1],
  },
}

export function createPortfolioPerformanceSeries(range, totalAccountValue, costBasis) {
  const pattern = portfolioPerformancePatterns[range] ?? portfolioPerformancePatterns['3M']

  return {
    labels: pattern.labels,
    totalAccountValue: pattern.totalAccountValue.map((multiplier) => totalAccountValue * multiplier),
    costBasis: pattern.costBasis.map((multiplier) => costBasis * multiplier),
  }
}

export const recentPortfolioTransactions = [
  { id: 'tx-1', date: '2026-07-10', type: 'Buy', symbol: 'NVDA', asset: 'NVIDIA Corporation', quantity: 2, price: 126.4 },
  { id: 'tx-2', date: '2026-07-05', type: 'Dividend', symbol: 'AAPL', asset: 'Apple Inc.', quantity: 12, price: 0.25 },
  { id: 'tx-3', date: '2026-06-28', type: 'Buy', symbol: 'SPY', asset: 'SPDR S&P 500 ETF', quantity: 1.32, price: 552.1 },
  { id: 'tx-4', date: '2026-06-14', type: 'Sell', symbol: 'MSFT', asset: 'Microsoft Corporation', quantity: 1, price: 455.2 },
  { id: 'tx-5', date: '2026-06-02', type: 'Buy', symbol: 'AAPL', asset: 'Apple Inc.', quantity: 2, price: 181.75 },
]
