export const navigationItems = [
  { id: 'dashboard', label: 'Dashboard', icon: 'dashboard' },
  { id: 'market-analysis', label: 'Market Analysis', icon: 'market' },
  { id: 'watchlist', label: 'Watchlist', icon: 'watchlist' },
  { id: 'portfolio', label: 'Portfolio', icon: 'portfolio' },
  { id: 'strategy-backtesting', label: 'Strategy Backtest', icon: 'strategy', path: '/backtest' },
  { id: 'ai-insights', label: 'AI Insights', icon: 'insights', path: '/ai-insights' },
]

export const workspaceContent = {
  dashboard: {
    eyebrow: 'Dashboard workspace',
    title: 'Your investment overview will live here',
    description:
      'Market data, portfolio metrics, strategy results and AI insights will be added in the next development stages.',
    icon: 'market',
  },
  'market-analysis': {
    eyebrow: 'Market analysis',
    title: 'Market intelligence will live here',
    description: 'Mock market trends, asset snapshots and analysis modules will be presented in this workspace.',
    icon: 'market',
  },
  watchlist: {
    eyebrow: 'Watchlist',
    title: 'Track selected stocks',
    description: 'Review the latest mock market and technical status for stocks you follow.',
    icon: 'watchlist',
  },
  portfolio: {
    eyebrow: 'Portfolio',
    title: 'Portfolio tracking will live here',
    description: 'Mock holdings, allocation and performance summaries will be presented in this workspace.',
    icon: 'portfolio',
  },
  'strategy-backtesting': {
    eyebrow: 'Strategy backtesting',
    title: 'Backtesting results will live here',
    description: 'Mock strategy parameters, historical runs and performance results will be presented here.',
    icon: 'strategy',
  },
  'ai-insights': {
    eyebrow: 'AI insights',
    title: 'AI-assisted insights will live here',
    description: 'Mock research summaries, signals and explainable investment insights will be presented here.',
    icon: 'insights',
  },
}

export const mockSystemStatus = {
  label: 'System online',
  detail: 'All services operational',
}

export const priceChart = {
  symbol: 'AAPL',
  company: 'Apple Inc.',
  price: '$189.84',
  change: '+$2.41',
  percent: '+1.29%',
  ranges: ['1D', '1W', '1M', '3M', '1Y'],
  labels: {
    '1D': ['09:30', '11:00', '12:30', '14:00', '16:00'],
    '1W': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
    '1M': ['Jun 10', 'Jun 17', 'Jun 24', 'Jul 1', 'Jul 8'],
    '3M': ['Apr', 'May', 'Jun', 'Jul', 'Now'],
    '1Y': ['Jul', 'Oct', 'Jan', 'Apr', 'Jul'],
  },
  series: {
    '1D': [186.4, 186.9, 186.6, 187.3, 187.1, 188.0, 187.7, 188.5, 188.2, 189.1, 188.8, 189.4, 189.2, 189.8, 189.6, 189.84],
    '1W': [181.2, 182.8, 182.1, 183.7, 184.9, 184.3, 185.8, 186.2, 185.6, 187.1, 187.8, 188.6, 188.2, 189.1, 189.84],
    '1M': [176.4, 178.2, 177.5, 180.1, 181.8, 180.9, 183.6, 182.7, 185.2, 184.6, 186.8, 187.5, 186.9, 188.7, 189.84],
    '3M': [169.8, 172.4, 171.1, 175.6, 174.2, 178.9, 181.5, 179.7, 183.8, 182.6, 185.9, 184.8, 187.2, 188.4, 189.84],
    '1Y': [194.1, 188.2, 181.6, 185.3, 178.4, 172.7, 176.9, 182.1, 179.3, 184.8, 181.9, 186.5, 184.2, 188.1, 189.84],
  },
}

export const technicalIndicators = {
  signal: 'Moderately bullish',
  score: 72,
  items: [
    { name: 'RSI (14)', value: '58.4', signal: 'Neutral', tone: 'neutral', level: 58 },
    { name: 'MACD', value: '+1.24', signal: 'Bullish', tone: 'positive', level: 76 },
    { name: 'Moving Avg. (50)', value: '$184.62', signal: 'Above', tone: 'positive', level: 82 },
    { name: 'Volatility', value: '21.3%', signal: 'Moderate', tone: 'warning', level: 44 },
  ],
}

export const watchlist = [
  { symbol: 'NVDA', name: 'NVIDIA', price: '$131.88', change: '+2.74%', direction: 'up', trend: [38, 43, 40, 48, 51, 49, 58, 61, 67] },
  { symbol: 'MSFT', name: 'Microsoft', price: '$449.52', change: '+0.64%', direction: 'up', trend: [44, 46, 45, 48, 50, 53, 51, 55, 57] },
  { symbol: 'TSLA', name: 'Tesla', price: '$248.23', change: '-1.18%', direction: 'down', trend: [68, 64, 66, 61, 59, 62, 56, 54, 51] },
  { symbol: 'AMZN', name: 'Amazon', price: '$199.34', change: '+1.41%', direction: 'up', trend: [36, 39, 42, 40, 46, 49, 53, 52, 58] },
  { symbol: 'GOOGL', name: 'Alphabet', price: '$191.18', change: '-0.32%', direction: 'down', trend: [58, 61, 59, 57, 60, 56, 54, 55, 52] },
]

export const portfolioSummary = {
  totalAccountValue: '$124,680.45',
  holdingsValue: '$112,230.45',
  availableFunds: '$12,450.00',
  dayChange: '+1.82%',
  dayChangeValue: '+$2,231.18 today',
  totalGain: '+$18,420.30',
  totalGainPercent: '+17.33%',
  allocations: [
    { label: 'Stocks', value: 53.34, color: '#6877f5' },
    { label: 'ETFs', value: 46.66, color: '#2bbf8a' },
  ],
}

export const dashboardData = {
  priceChart,
  technicalIndicators,
  watchlist,
  portfolioSummary,
}
