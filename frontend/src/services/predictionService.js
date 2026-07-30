import {
  defaultPredictionConfig,
  forecastHorizonOptions,
  historicalWindowOptions,
  predictionAssets,
  predictionDisclaimer,
  predictionModelOptions,
} from '../data/predictionMockData'

const ensembleWeights = {
  'logistic-regression': 0.25,
  'random-forest': 0.35,
  xgboost: 0.4,
}

const assetModelFit = {
  AAPL: { 'logistic-regression': 1, 'random-forest': 1, xgboost: 2 },
  MSFT: { 'logistic-regression': 1, 'random-forest': 3, xgboost: 1 },
  NVDA: { 'logistic-regression': -2, 'random-forest': 1, xgboost: 4 },
  SPY: { 'logistic-regression': 4, 'random-forest': 1, xgboost: -1 },
  QQQ: { 'logistic-regression': 0, 'random-forest': 3, xgboost: 2 },
}

const horizonModelFit = {
  '1-day': { 'logistic-regression': 3, 'random-forest': 0, xgboost: -1 },
  '5-days': { 'logistic-regression': 0, 'random-forest': 1, xgboost: 2 },
  '10-days': { 'logistic-regression': -1, 'random-forest': 3, xgboost: 1 },
  '20-days': { 'logistic-regression': 3, 'random-forest': 1, xgboost: -2 },
}

const anchorDate = '2026-07-16'

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum)
}

function round(value, precision = 0) {
  const multiplier = 10 ** precision
  return Math.round((value + Number.EPSILON) * multiplier) / multiplier
}

function formatSignedPercent(value) {
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}

function findOption(options, value, fallbackValue) {
  return options.find((option) => option.value === value)
    ?? options.find((option) => option.value === fallbackValue)
    ?? options[0]
}

function normalizeConfig(config = {}) {
  const asset = predictionAssets.find((item) => item.symbol === config.assetSymbol)
    ?? predictionAssets.find((item) => item.symbol === defaultPredictionConfig.assetSymbol)
  const horizon = findOption(forecastHorizonOptions, config.horizon, defaultPredictionConfig.horizon)
  const model = findOption(predictionModelOptions, config.model, defaultPredictionConfig.model)
  const historicalWindow = findOption(
    historicalWindowOptions,
    config.historicalWindow,
    defaultPredictionConfig.historicalWindow,
  )

  return {
    assetSymbol: asset.symbol,
    horizon: horizon.value,
    horizonLabel: horizon.label,
    model: model.value,
    modelLabel: model.label,
    historicalWindow: historicalWindow.value,
    historicalWindowLabel: historicalWindow.label,
    includeTechnicalIndicators: config.includeTechnicalIndicators !== false,
    includeMarketContext: config.includeMarketContext !== false,
  }
}

function getTechnicalAdjustment(asset) {
  const { technical } = asset
  let adjustment = 0

  adjustment += technical.macd === 'Positive' ? 3 : technical.macd === 'Negative' ? -3 : 0
  adjustment += technical.priceVsMA20 === 'Above' ? 3 : technical.priceVsMA20 === 'Below' ? -3 : 0
  adjustment += technical.rsi >= 70 ? -4 : technical.rsi >= 65 ? -2 : technical.rsi <= 35 ? 1 : 0
  adjustment += technical.recentReturn >= 2 ? 2 : technical.recentReturn > 0 ? 1 : technical.recentReturn <= -2 ? -2 : technical.recentReturn < 0 ? -1 : 0

  return adjustment
}

function getDirection(probability) {
  if (probability >= 58) return 'Up'
  if (probability <= 42) return 'Down'
  return 'Neutral'
}

function getModelMetrics(model, asset, horizon, historicalWindow) {
  const modelFit = (assetModelFit[asset.symbol]?.[model.value] ?? 0)
    + (horizonModelFit[horizon.value]?.[model.value] ?? 0)
  const adjustment = asset.testAdjustment
    + historicalWindow.performanceAdjustment
    - horizon.performancePenalty
    + modelFit
  const volatilityPenalty = asset.volatility === 'High'
    ? model.value === 'xgboost' ? 3 : 1
    : asset.volatility === 'Elevated' ? 1 : 0

  return {
    accuracy: clamp(model.accuracy + adjustment, 48, 70),
    precision: clamp(model.precision + adjustment, 47, 70),
    recall: clamp(model.recall + adjustment, 48, 72),
    f1: clamp(model.f1 + adjustment, 48, 70),
    rocAuc: clamp(round(model.rocAuc + adjustment / 100, 2), 0.5, 0.78),
    stability: clamp(model.stability + modelFit - volatilityPenalty, 55, 92),
  }
}

function weightedMetric(rows, key, precision = 0) {
  return round(rows.reduce((total, row) => total + row[key] * ensembleWeights[row.key], 0), precision)
}

function createModelComparison(asset, config, horizon, historicalWindow) {
  const technicalAdjustment = config.includeTechnicalIndicators ? getTechnicalAdjustment(asset) : 0
  const marketAdjustment = config.includeMarketContext ? asset.marketBias : 0
  const commonProbability = asset.baseProbability
    + technicalAdjustment
    + marketAdjustment
    + horizon.probabilityAdjustment

  const baseRows = predictionModelOptions.slice(0, 3).map((model) => {
    const metrics = getModelMetrics(model, asset, horizon, historicalWindow)
    const probabilityIncrease = clamp(
      Math.round(commonProbability + model.probabilityAdjustment),
      25,
      75,
    )

    return {
      key: model.value,
      label: model.label,
      predictedDirection: getDirection(probabilityIncrease),
      probabilityIncrease,
      expectedReturn: round((probabilityIncrease - 50) * 0.13 * Math.sqrt(horizon.days / 5), 1),
      ...metrics,
    }
  })

  const ensembleProbability = Math.round(weightedMetric(baseRows, 'probabilityIncrease', 2))
  const baseDirectionsAligned = new Set(baseRows.map((model) => model.predictedDirection)).size === 1
  const ensembleRow = {
    key: 'ensemble',
    label: 'Ensemble',
    predictedDirection: getDirection(ensembleProbability),
    probabilityIncrease: ensembleProbability,
    expectedReturn: round((ensembleProbability - 50) * 0.13 * Math.sqrt(horizon.days / 5), 1),
    accuracy: weightedMetric(baseRows, 'accuracy'),
    precision: weightedMetric(baseRows, 'precision'),
    recall: weightedMetric(baseRows, 'recall'),
    f1: weightedMetric(baseRows, 'f1'),
    rocAuc: weightedMetric(baseRows, 'rocAuc', 2),
    stability: clamp(weightedMetric(baseRows, 'stability') + (baseDirectionsAligned ? 4 : -3), 55, 92),
  }

  return [...baseRows, ensembleRow]
}

function createModelAgreement(modelComparison) {
  const directionCounts = modelComparison.reduce((counts, model) => ({
    ...counts,
    [model.predictedDirection]: (counts[model.predictedDirection] ?? 0) + 1,
  }), {})
  const [dominantDirection, dominantCount] = Object.entries(directionCounts)
    .sort((left, right) => right[1] - left[1])[0]
  const probabilities = modelComparison.map((model) => model.probabilityIncrease)
  const minimumProbability = Math.min(...probabilities)
  const maximumProbability = Math.max(...probabilities)
  const spread = maximumProbability - minimumProbability
  const accuracies = modelComparison.map((model) => model.accuracy)
  const rocAucValues = modelComparison.map((model) => model.rocAuc)
  const validationDisagreement = Math.max(...accuracies) - Math.min(...accuracies) >= 12
    || Math.max(...rocAucValues) - Math.min(...rocAucValues) >= 0.15
  const significantDisagreement = spread >= 12
    || (directionCounts.Up && directionCounts.Down)
    || validationDisagreement
  const agreement = significantDisagreement
    ? 'Weak'
    : dominantCount === 4 && spread <= 8
    ? 'Strong'
    : dominantCount >= 3
      ? 'Moderate'
      : 'Weak'
  const directionPhrase = dominantDirection === 'Up'
    ? 'an upward direction'
    : dominantDirection === 'Down'
      ? 'a downward direction'
      : 'a neutral direction'

  return {
    agreement,
    dominantDirection,
    dominantCount,
    probabilityRange: `${minimumProbability}% - ${maximumProbability}%`,
    significantDisagreement: Boolean(significantDisagreement),
    summary: `${dominantCount} of 4 models predict ${directionPhrase}.`,
  }
}

function getAutomaticSelectionScore(model, modelAgreement) {
  const agreementScore = model.predictedDirection === modelAgreement.dominantDirection
    ? modelAgreement.agreement === 'Strong' ? 100 : modelAgreement.agreement === 'Moderate' ? 82 : 68
    : 35

  return model.accuracy * 0.3
    + model.f1 * 0.25
    + model.rocAuc * 100 * 0.3
    + model.stability * 0.1
    + agreementScore * 0.05
}

function selectAutomaticModel(modelComparison, modelAgreement) {
  const baseModels = modelComparison.slice(0, 3)
  const rankedBaseModels = baseModels
    .map((model) => ({ model, score: getAutomaticSelectionScore(model, modelAgreement) }))
    .sort((left, right) => right.score - left.score || left.model.key.localeCompare(right.model.key))
  const bestBaseModel = rankedBaseModels[0]
  const weakestBaseModel = rankedBaseModels[rankedBaseModels.length - 1]
  const ensemble = modelComparison.find((model) => model.key === 'ensemble')
  const ensembleScore = getAutomaticSelectionScore(ensemble, modelAgreement)
  const baseDirectionsAligned = new Set(baseModels.map((model) => model.predictedDirection)).size === 1
  const basePerformanceIsClose = bestBaseModel.score - weakestBaseModel.score <= 3.25
  const shouldUseEnsemble = baseDirectionsAligned
    && basePerformanceIsClose
    && ensembleScore >= bestBaseModel.score - 1.5

  if (shouldUseEnsemble) {
    return {
      model: ensemble,
      reason: 'Ensemble was selected because the three base models produced closely matched simulated validation performance and a consistent direction, so combining their outputs improved stability.',
    }
  }

  return {
    model: bestBaseModel.model,
    reason: `${bestBaseModel.model.label} was selected because it produced the strongest simulated validation performance for the selected asset and forecast horizon, balancing ROC-AUC, F1 score, test accuracy, stability, and model agreement.`,
  }
}

function getConfidence({ asset, config, horizon, selectedModel, modelAgreement }) {
  let score = 0
  score += config.includeTechnicalIndicators && config.includeMarketContext ? 1 : config.includeTechnicalIndicators || config.includeMarketContext ? 0 : -1
  score += modelAgreement.agreement === 'Strong' ? 2 : modelAgreement.agreement === 'Moderate' ? 1 : -1
  score += selectedModel.accuracy >= 60 ? 1 : selectedModel.accuracy < 55 ? -1 : 0
  score += asset.volatility === 'High' ? -2 : asset.volatility === 'Elevated' ? -1 : asset.volatility === 'Low' ? 1 : 0
  score += horizon.days === 1 ? 1 : horizon.days === 10 ? -1 : horizon.days === 20 ? -2 : 0
  score += selectedModel.probabilityIncrease >= 58 || selectedModel.probabilityIncrease <= 42 ? 1 : -1
  score += modelAgreement.significantDisagreement ? -2 : 0

  return score >= 4 ? 'High' : score >= 0 ? 'Medium' : 'Low'
}

function parseDate(value) {
  return new Date(`${value}T00:00:00Z`)
}

function toDateString(date) {
  return date.toISOString().slice(0, 10)
}

function isBusinessDay(date) {
  const day = date.getUTCDay()
  return day !== 0 && day !== 6
}

function createHistoricalDates(count) {
  const dates = []
  const cursor = parseDate(anchorDate)

  while (dates.length < count) {
    if (isBusinessDay(cursor)) dates.unshift(toDateString(cursor))
    cursor.setUTCDate(cursor.getUTCDate() - 1)
  }

  return dates
}

function createFutureDates(count) {
  const dates = []
  const cursor = parseDate(anchorDate)

  while (dates.length < count) {
    cursor.setUTCDate(cursor.getUTCDate() + 1)
    if (isBusinessDay(cursor)) dates.push(toDateString(cursor))
  }

  return dates
}

function createForecastSeries(asset, horizon, model, expectedReturn, rangeHalfWidth) {
  const historicalDates = createHistoricalDates(asset.historicalPrices.length)
  const historical = asset.historicalPrices.map((price, index) => ({
    date: historicalDates[index],
    type: 'historical',
    price,
  }))
  const futureDates = createFutureDates(horizon.days)
  const seed = asset.symbol.split('').reduce((total, character) => total + character.charCodeAt(0), 0)
  const forecast = [
    {
      date: anchorDate,
      type: 'forecast',
      expectedPrice: asset.currentPrice,
      lowerBound: asset.currentPrice,
      upperBound: asset.currentPrice,
    },
    ...futureDates.map((date, index) => {
      const progress = (index + 1) / horizon.days
      const wave = Math.sin(progress * Math.PI) * Math.sin(seed + index * 1.7) * asset.volatilityRate * 18
      const progressiveReturn = expectedReturn * progress + wave
      const expectedPrice = asset.currentPrice * (1 + progressiveReturn / 100)
      const progressiveRange = rangeHalfWidth * Math.sqrt(progress) * model.rangeMultiplier

      return {
        date,
        type: 'forecast',
        expectedPrice: round(expectedPrice, 2),
        lowerBound: round(expectedPrice - progressiveRange, 2),
        upperBound: round(expectedPrice + progressiveRange, 2),
      }
    }),
  ]

  return { historical, forecast }
}

function createScenarios(asset, selectedModel, expectedReturn, rangeHalfWidth) {
  const probability = selectedModel.probabilityIncrease
  const bullProbability = clamp(22 + Math.round((probability - 50) * 0.35), 15, 35)
  const bearProbability = clamp(22 + Math.round((50 - probability) * 0.35), 15, 35)
  const baseProbability = 100 - bullProbability - bearProbability
  const rangePercent = (rangeHalfWidth / asset.currentPrice) * 100
  const bullReturn = round(expectedReturn + Math.max(1.2, rangePercent * 0.75), 1)
  const bearReturn = round(expectedReturn - Math.max(1.2, rangePercent * 0.85), 1)

  return [
    {
      key: 'bull',
      title: 'Bull Scenario',
      estimatedPrice: round(asset.currentPrice * (1 + bullReturn / 100), 2),
      potentialReturn: bullReturn,
      probability: bullProbability,
      assumptions: 'Momentum persists, market context improves, and volatility does not expand further.',
    },
    {
      key: 'base',
      title: 'Base Scenario',
      estimatedPrice: round(asset.currentPrice * (1 + expectedReturn / 100), 2),
      potentialReturn: expectedReturn,
      probability: baseProbability,
      assumptions: 'Current trend and volatility conditions remain broadly stable through the forecast horizon.',
    },
    {
      key: 'bear',
      title: 'Bear Scenario',
      estimatedPrice: round(asset.currentPrice * (1 + bearReturn / 100), 2),
      potentialReturn: bearReturn,
      probability: bearProbability,
      assumptions: 'Momentum weakens, risk sentiment deteriorates, or volatility expands beyond the recent range.',
    },
  ]
}

function directionFromValue(value, positiveThreshold = 0) {
  if (value > positiveThreshold) return 'Positive'
  if (value < -positiveThreshold) return 'Negative'
  return 'Neutral'
}

function createFeatureInfluence(asset, config) {
  const features = []
  const technical = asset.technical

  if (config.includeTechnicalIndicators) {
    features.push(
      {
        name: 'Price vs MA20',
        direction: technical.priceVsMA20 === 'Above' ? 'Positive' : technical.priceVsMA20 === 'Below' ? 'Negative' : 'Neutral',
        importance: 'High',
        explanation: `Price is ${technical.priceVsMA20.toLowerCase()} the 20-period moving average in the simulated input.`,
      },
      {
        name: 'RSI',
        direction: technical.rsi >= 70 ? 'Negative' : technical.rsi >= 65 ? 'Neutral' : technical.rsi <= 35 ? 'Positive' : 'Neutral',
        importance: technical.rsi >= 65 || technical.rsi <= 35 ? 'High' : 'Medium',
        explanation: technical.rsi >= 70
          ? `RSI at ${technical.rsi} reduces short-term upside probability and widens uncertainty.`
          : `RSI at ${technical.rsi} does not create an extreme momentum signal.`,
      },
      {
        name: 'MACD Momentum',
        direction: technical.macd,
        importance: 'High',
        explanation: `${technical.macd} MACD momentum ${technical.macd === 'Positive' ? 'increases' : technical.macd === 'Negative' ? 'reduces' : 'does not materially change'} the probability of an upward forecast.`,
      },
    )
  }

  features.push(
    {
      name: 'Recent Return',
      direction: directionFromValue(technical.recentReturn, 0.3),
      importance: 'Medium',
      explanation: `The recent simulated return is ${formatSignedPercent(technical.recentReturn)}.`,
    },
    {
      name: 'Volume Change',
      direction: directionFromValue(technical.volumeChange, 2),
      importance: 'Low',
      explanation: `Recent mock volume changed ${formatSignedPercent(technical.volumeChange)} versus its comparison period.`,
    },
    {
      name: 'Historical Volatility',
      direction: asset.volatility === 'High' || asset.volatility === 'Elevated' ? 'Negative' : 'Neutral',
      importance: 'High',
      explanation: `${asset.volatility} volatility increases the width of the simulated forecast range.`,
    },
  )

  if (config.includeMarketContext) {
    features.push({
      name: 'Market Trend',
      direction: asset.marketBias > 0 ? 'Positive' : asset.marketBias < 0 ? 'Negative' : 'Neutral',
      importance: 'Medium',
      explanation: `${asset.market.trend} market conditions are included in the directional probability.`,
    })
  }

  return features
}

function createReliability(asset, config, horizon, selectedModel, modelAgreement, confidence) {
  const includedContexts = Number(config.includeTechnicalIndicators) + Number(config.includeMarketContext)
  const dataCompleteness = includedContexts === 2 ? 'High' : includedContexts === 1 ? 'Medium' : 'Low'
  const agreementLevel = modelAgreement.agreement === 'Strong' ? 'High' : modelAgreement.agreement === 'Moderate' ? 'Medium' : 'Low'
  const performanceLevel = selectedModel.accuracy >= 60 ? 'High' : selectedModel.accuracy >= 55 ? 'Medium' : 'Low'
  const horizonRisk = horizon.days === 1 ? 'Low' : horizon.days === 20 ? 'High' : 'Medium'
  const volatilityUncertainty = asset.volatility === 'High' ? 'High' : asset.volatility === 'Elevated' ? 'Medium' : 'Low'

  return {
    summary: `Forecast confidence is ${confidence} because the underlying forecast signals show ${modelAgreement.agreement.toLowerCase()} consistency, while ${asset.volatility.toLowerCase()} volatility and the ${horizon.label.toLowerCase()} forecast horizon shape uncertainty.`,
    items: [
      {
        label: 'Data Completeness',
        value: dataCompleteness,
        detail: includedContexts === 2 ? 'Technical indicators and market context are included.' : `${includedContexts} of 2 optional context groups are included.`,
        tone: dataCompleteness === 'High' ? 'positive' : dataCompleteness === 'Medium' ? 'warning' : 'negative',
      },
      {
        label: 'Forecast Consistency',
        value: agreementLevel,
        detail: `${modelAgreement.agreement} consistency across the underlying forecast signals.`,
        tone: agreementLevel === 'High' ? 'positive' : agreementLevel === 'Medium' ? 'warning' : 'negative',
      },
      {
        label: 'Simulated Reliability',
        value: performanceLevel,
        detail: `Simulated validation evidence is ${performanceLevel.toLowerCase()} for the current configuration.`,
        tone: performanceLevel === 'High' ? 'positive' : performanceLevel === 'Medium' ? 'warning' : 'negative',
      },
      {
        label: 'Forecast Horizon Risk',
        value: horizonRisk,
        detail: `${horizon.label} ${horizonRisk === 'High' ? 'materially expands' : horizonRisk === 'Medium' ? 'adds' : 'limits'} horizon uncertainty.`,
        tone: horizonRisk === 'High' ? 'negative' : horizonRisk === 'Medium' ? 'warning' : 'positive',
      },
      {
        label: 'Volatility Uncertainty',
        value: volatilityUncertainty,
        detail: `${asset.volatility} recent volatility determines forecast range width.`,
        tone: volatilityUncertainty === 'High' ? 'negative' : volatilityUncertainty === 'Medium' ? 'warning' : 'positive',
      },
    ],
  }
}

function createInterpretation(asset, config, horizon, selectedModel, modelAgreement) {
  const probability = selectedModel.probabilityIncrease
  const directionalPhrase = selectedModel.predictedDirection === 'Up'
    ? probability >= 65 ? 'bullish' : 'moderately bullish'
    : selectedModel.predictedDirection === 'Down'
      ? probability <= 35 ? 'bearish' : 'moderately bearish'
      : 'neutral'
  const technicalText = config.includeTechnicalIndicators
    ? `${asset.technical.macd} MACD momentum, price ${asset.technical.priceVsMA20.toLowerCase()} MA20, and RSI at ${asset.technical.rsi} shape the direction.`
    : 'Technical indicators were excluded from this forecast.'
  const marketText = config.includeMarketContext
    ? `${asset.market.trend} market context and ${asset.market.relativeStrength.toLowerCase()} relative strength are included.`
    : 'Market context was excluded from this forecast.'
  const disagreementText = modelAgreement.significantDisagreement
    ? 'Underlying forecast signals differ significantly, which reduces confidence.'
    : `${modelAgreement.agreement} forecast consistency supports the stated confidence level.`
  const horizonPhrase = horizon.days === 1 ? 'one-day' : `${horizon.days}-trading-day`

  return `This deterministic mock forecast indicates a ${directionalPhrase} ${horizonPhrase} direction for ${asset.symbol} with a ${probability}% estimated probability of an increase. ${technicalText} ${marketText} ${asset.volatility} volatility widens the forecast interval. ${disagreementText}`
}

export function generateMockForecast(inputConfig = {}, generatedAt = new Date().toISOString()) {
  const normalizedConfiguration = normalizeConfig({ ...defaultPredictionConfig, ...inputConfig })
  const asset = predictionAssets.find((item) => item.symbol === normalizedConfiguration.assetSymbol)
  const horizon = findOption(forecastHorizonOptions, normalizedConfiguration.horizon, defaultPredictionConfig.horizon)
  const historicalWindow = findOption(
    historicalWindowOptions,
    normalizedConfiguration.historicalWindow,
    defaultPredictionConfig.historicalWindow,
  )
  const comparisonRows = createModelComparison(asset, normalizedConfiguration, horizon, historicalWindow)
  const modelAgreement = createModelAgreement(comparisonRows)
  const automaticSelection = selectAutomaticModel(comparisonRows, modelAgreement)
  const configuration = {
    ...normalizedConfiguration,
    model: automaticSelection.model.key,
    modelLabel: automaticSelection.model.label,
  }
  const modelComparison = comparisonRows.map((model) => ({
    ...model,
    confidence: getConfidence({ asset, config: configuration, horizon, selectedModel: model, modelAgreement }),
  }))
  const selectedModel = modelComparison.find((model) => model.key === configuration.model)
  const selectedModelDefinition = findOption(predictionModelOptions, configuration.model, defaultPredictionConfig.model)
  const confidence = selectedModel.confidence
  const expectedReturn = selectedModel.expectedReturn
  const expectedPrice = round(asset.currentPrice * (1 + expectedReturn / 100), 2)
  const contextMultiplier = (configuration.includeTechnicalIndicators ? 1 : 1.1)
    * (configuration.includeMarketContext ? 1 : 1.08)
  const rangeHalfWidth = asset.currentPrice
    * asset.volatilityRate
    * horizon.uncertaintyMultiplier
    * contextMultiplier
  const forecastRange = {
    lower: round(expectedPrice - rangeHalfWidth * selectedModelDefinition.rangeMultiplier, 2),
    upper: round(expectedPrice + rangeHalfWidth * selectedModelDefinition.rangeMultiplier, 2),
  }
  const forecastSeries = createForecastSeries(
    asset,
    horizon,
    selectedModelDefinition,
    expectedReturn,
    rangeHalfWidth,
  )
  const scenarios = createScenarios(asset, selectedModel, expectedReturn, rangeHalfWidth)
  const featureInfluence = createFeatureInfluence(asset, configuration)
  const reliability = createReliability(
    asset,
    configuration,
    horizon,
    selectedModel,
    modelAgreement,
    confidence,
  )
  const interpretation = createInterpretation(asset, configuration, horizon, selectedModel, modelAgreement)
  const id = [
    'forecast',
    configuration.assetSymbol,
    configuration.horizon,
    configuration.model,
    configuration.historicalWindow,
    configuration.includeTechnicalIndicators ? 'technical' : 'no-technical',
    configuration.includeMarketContext ? 'market' : 'no-market',
  ].join('-')

  return {
    id,
    asset: { symbol: asset.symbol, name: asset.name, type: asset.type },
    assetType: asset.type,
    configuration,
    generatedAt,
    selectedModel: selectedModel.label,
    modelSelectionMode: 'automatic',
    selectionReason: automaticSelection.reason,
    predictedDirection: selectedModel.predictedDirection,
    probabilityIncrease: selectedModel.probabilityIncrease,
    expectedReturn,
    currentPrice: asset.currentPrice,
    expectedPrice,
    forecastRange,
    expectedVolatility: asset.volatility,
    confidence,
    priceSummary: `The deterministic mock forecast indicates a ${selectedModel.predictedDirection === 'Up' ? 'moderately positive' : selectedModel.predictedDirection === 'Down' ? 'moderately negative' : 'balanced'} ${horizon.days <= 5 ? 'short-term' : 'forward'} direction, but the forecast range remains ${asset.volatility === 'High' || asset.volatility === 'Elevated' ? 'wide' : 'uncertain'} because recent volatility is ${asset.volatility.toLowerCase()}.`,
    forecastSeries,
    modelComparison,
    modelAgreement,
    scenarios,
    featureInfluence,
    reliability,
    modelPerformance: {
      accuracy: selectedModel.accuracy,
      precision: selectedModel.precision,
      recall: selectedModel.recall,
      f1: selectedModel.f1,
      rocAuc: selectedModel.rocAuc,
      stability: selectedModel.stability,
      baselineAccuracy: clamp(52 + asset.baselineAdjustment + historicalWindow.performanceAdjustment, 48, 58),
    },
    interpretation,
    disclaimer: predictionDisclaimer,
  }
}

export function sanitizeForecastHistory(value) {
  if (!Array.isArray(value)) return []

  return value.filter((forecast) => (
    forecast
    && typeof forecast.id === 'string'
    && typeof forecast.generatedAt === 'string'
    && typeof forecast.configuration === 'object'
    && typeof forecast.asset?.symbol === 'string'
    && Array.isArray(forecast.forecastSeries?.historical)
    && Array.isArray(forecast.forecastSeries?.forecast)
    && Array.isArray(forecast.modelComparison)
    && Array.isArray(forecast.scenarios)
  ))
}

export function createPredictionContext(forecast) {
  const horizon = forecastHorizonOptions.find(
    (option) => option.value === forecast.configuration?.horizon,
  )

  return {
    ...forecast,
    source: 'Prediction Lab',
    type: 'rule-based-mock-forecast',
    id: forecast.id,
    forecastId: forecast.id,
    forecastHorizon: horizon?.label ?? forecast.configuration?.horizon,
    volatility: forecast.expectedVolatility,
  }
}
