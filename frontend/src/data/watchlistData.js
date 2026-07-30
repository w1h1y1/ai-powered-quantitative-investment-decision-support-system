export const watchlistStorageKey = 'aiquantification.watchlist.symbols'

export const defaultWatchlistSymbols = ['AAPL', 'MSFT', 'NVDA', 'TSLA']

const watchlistMetadata = {
  AAPL: {
    company: 'Apple Inc.',
    rsiStatus: 'Neutral',
    macdStatus: 'Bullish',
    overallTrend: 'Uptrend',
  },
  MSFT: {
    company: 'Microsoft Corporation',
    rsiStatus: 'Near Overbought',
    macdStatus: 'Bullish',
    overallTrend: 'Uptrend',
  },
  NVDA: {
    company: 'NVIDIA Corporation',
    rsiStatus: 'Near Overbought',
    macdStatus: 'Bullish',
    overallTrend: 'Uptrend',
  },
  AMZN: {
    company: 'Amazon.com Inc.',
    rsiStatus: 'Neutral',
    macdStatus: 'Bullish',
    overallTrend: 'Uptrend',
  },
  GOOGL: {
    company: 'Alphabet Inc.',
    rsiStatus: 'Near Oversold',
    macdStatus: 'Bearish',
    overallTrend: 'Downtrend',
  },
  TSLA: {
    company: 'Tesla Inc.',
    rsiStatus: 'Near Oversold',
    macdStatus: 'Bearish',
    overallTrend: 'Downtrend',
  },
  META: {
    company: 'Meta Platforms Inc.',
    rsiStatus: 'Neutral',
    macdStatus: 'Neutral',
    overallTrend: 'Sideways',
  },
}

function parseSignedValue(value) {
  const parsed = Number(String(value).replace(/[^0-9.-]/g, ''))
  return Number.isFinite(parsed) ? parsed : 0
}

export function createWatchlistUniverse(stocks) {
  return stocks.filter((stock) => watchlistMetadata[stock.symbol]).map((stock) => {
    const metadata = watchlistMetadata[stock.symbol] ?? {}
    const trend = stock.history?.['1M']?.['1D']?.closes?.slice(-18) ?? [stock.price, stock.price]

    return {
      symbol: stock.symbol,
      company: metadata.company ?? stock.company,
      price: stock.price,
      dailyChange: parseSignedValue(stock.change),
      changePercent: parseSignedValue(stock.percent),
      direction: stock.direction,
      trend,
      rsiStatus: metadata.rsiStatus ?? 'Neutral',
      macdStatus: metadata.macdStatus ?? 'Neutral',
      overallTrend: metadata.overallTrend ?? 'Sideways',
    }
  })
}
