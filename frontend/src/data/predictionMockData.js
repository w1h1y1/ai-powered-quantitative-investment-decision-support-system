export const predictionAssets = [
  {
    symbol: 'AAPL',
    name: 'Apple Inc.',
    type: 'Stock',
    currentPrice: 218.4,
    baseProbability: 51,
    marketBias: 2,
    testAdjustment: 0,
    baselineAdjustment: 0,
    volatility: 'Elevated',
    volatilityRate: 0.038,
    technical: {
      rsi: 67.4,
      macd: 'Positive',
      priceVsMA20: 'Above',
      recentReturn: 2.4,
      volumeChange: 8.5,
    },
    market: {
      trend: 'Constructive',
      relativeStrength: 'Above market',
      description: 'Large-cap technology conditions remain constructive, although momentum is no longer accelerating.',
    },
    historicalPrices: [
      205.2, 206.7, 205.9, 208.1, 207.4, 209.8, 211.2, 210.5, 212.7, 214.1,
      213.2, 215.6, 214.9, 216.8, 215.7, 217.2, 216.4, 219.1, 217.6, 218.4,
    ],
  },
  {
    symbol: 'MSFT',
    name: 'Microsoft Corp.',
    type: 'Stock',
    currentPrice: 512.3,
    baseProbability: 53,
    marketBias: 3,
    testAdjustment: 2,
    baselineAdjustment: 1,
    volatility: 'Moderate',
    volatilityRate: 0.029,
    technical: {
      rsi: 58.6,
      macd: 'Positive',
      priceVsMA20: 'Above',
      recentReturn: 1.6,
      volumeChange: 4.2,
    },
    market: {
      trend: 'Supportive',
      relativeStrength: 'Above market',
      description: 'Software and cloud momentum remain supportive in the current simulated market context.',
    },
    historicalPrices: [
      486.4, 488.7, 487.2, 491.3, 493.1, 492.4, 496.8, 498.2, 497.5, 501.6,
      503.4, 502.1, 505.7, 507.9, 506.8, 509.4, 508.6, 511.7, 510.2, 512.3,
    ],
  },
  {
    symbol: 'NVDA',
    name: 'NVIDIA Corp.',
    type: 'Stock',
    currentPrice: 173.45,
    baseProbability: 50,
    marketBias: 1,
    testAdjustment: 1,
    baselineAdjustment: 0,
    volatility: 'High',
    volatilityRate: 0.061,
    technical: {
      rsi: 72.8,
      macd: 'Positive',
      priceVsMA20: 'Above',
      recentReturn: 3.1,
      volumeChange: 15.4,
    },
    market: {
      trend: 'Positive with caution',
      relativeStrength: 'Strong',
      description: 'Semiconductor momentum is positive, but valuation sensitivity and high volatility increase uncertainty.',
    },
    historicalPrices: [
      158.2, 161.7, 159.4, 164.8, 162.6, 166.9, 169.1, 165.8, 171.4, 168.7,
      174.2, 170.6, 176.1, 172.8, 178.4, 175.2, 180.3, 176.7, 171.9, 173.45,
    ],
  },
  {
    symbol: 'SPY',
    name: 'SPDR S&P 500 ETF',
    type: 'ETF',
    currentPrice: 624.2,
    baseProbability: 50,
    marketBias: 0,
    testAdjustment: -1,
    baselineAdjustment: 1,
    volatility: 'Moderate',
    volatilityRate: 0.022,
    technical: {
      rsi: 46.3,
      macd: 'Negative',
      priceVsMA20: 'Below',
      recentReturn: -1.1,
      volumeChange: -3.8,
    },
    market: {
      trend: 'Sideways',
      relativeStrength: 'Near market',
      description: 'Broad market breadth is mixed and the index is consolidating near its recent range.',
    },
    historicalPrices: [
      629.8, 631.2, 630.5, 633.1, 631.7, 634.4, 632.6, 630.9, 629.2, 631.5,
      628.7, 627.4, 629.1, 626.8, 625.6, 627.2, 624.8, 626.1, 623.5, 624.2,
    ],
  },
  {
    symbol: 'QQQ',
    name: 'Invesco QQQ Trust',
    type: 'ETF',
    currentPrice: 555.8,
    baseProbability: 49,
    marketBias: 1,
    testAdjustment: 1,
    baselineAdjustment: 1,
    volatility: 'Elevated',
    volatilityRate: 0.034,
    technical: {
      rsi: 63.9,
      macd: 'Positive',
      priceVsMA20: 'Above',
      recentReturn: 1.3,
      volumeChange: 6.7,
    },
    market: {
      trend: 'Constructive',
      relativeStrength: 'Above market',
      description: 'Growth exposure remains supported, while concentration in large technology holdings adds sensitivity.',
    },
    historicalPrices: [
      531.7, 534.9, 533.1, 537.8, 539.6, 538.2, 542.7, 544.1, 541.9, 546.3,
      548.7, 546.8, 550.2, 552.6, 549.4, 553.8, 551.7, 557.1, 554.2, 555.8,
    ],
  },
]

export const forecastHorizonOptions = [
  { value: '1-day', label: '1 Trading Day', days: 1, probabilityAdjustment: 1, uncertaintyMultiplier: 0.58, performancePenalty: 0 },
  { value: '5-days', label: '5 Trading Days', days: 5, probabilityAdjustment: 0, uncertaintyMultiplier: 1, performancePenalty: 0 },
  { value: '10-days', label: '10 Trading Days', days: 10, probabilityAdjustment: -1, uncertaintyMultiplier: 1.38, performancePenalty: 1 },
  { value: '20-days', label: '20 Trading Days', days: 20, probabilityAdjustment: -2, uncertaintyMultiplier: 1.9, performancePenalty: 2 },
]

export const predictionModelOptions = [
  {
    value: 'logistic-regression',
    label: 'Logistic Regression',
    probabilityAdjustment: -4,
    rangeMultiplier: 0.92,
    accuracy: 54,
    precision: 53,
    recall: 55,
    f1: 54,
    rocAuc: 0.57,
    stability: 84,
  },
  {
    value: 'random-forest',
    label: 'Random Forest',
    probabilityAdjustment: 1,
    rangeMultiplier: 1.04,
    accuracy: 58,
    precision: 57,
    recall: 60,
    f1: 58,
    rocAuc: 0.62,
    stability: 78,
  },
  {
    value: 'xgboost',
    label: 'XGBoost',
    probabilityAdjustment: 4,
    rangeMultiplier: 1.08,
    accuracy: 61,
    precision: 60,
    recall: 63,
    f1: 61,
    rocAuc: 0.66,
    stability: 74,
  },
  {
    value: 'ensemble',
    label: 'Ensemble',
    rangeMultiplier: 1.02,
  },
]

export const historicalWindowOptions = [
  { value: '6-months', label: '6 Months', performanceAdjustment: -2 },
  { value: '1-year', label: '1 Year', performanceAdjustment: -1 },
  { value: '2-years', label: '2 Years', performanceAdjustment: 0 },
  { value: '5-years', label: '5 Years', performanceAdjustment: 1 },
]

export const defaultPredictionConfig = {
  assetSymbol: 'AAPL',
  horizon: '5-days',
  model: 'xgboost',
  historicalWindow: '2-years',
  includeTechnicalIndicators: true,
  includeMarketContext: true,
}

export const predictionHistoryStorageKey = 'aiquantification.predictionLab.history'
export const selectedForecastStorageKey = 'aiquantification.predictionLab.selectedForecastId'
export const latestPredictionContextStorageKey = 'latestPredictionContext'
export const latestPredictionContextUpdatedEvent = 'aiquantification:latestPredictionContextUpdated'
export const predictionHistoryLimit = 12

export const predictionDisclaimer =
  'Rule-based demo forecasts are probabilistic simulations based on historical and mock information. They do not guarantee future market performance or constitute financial advice.'
