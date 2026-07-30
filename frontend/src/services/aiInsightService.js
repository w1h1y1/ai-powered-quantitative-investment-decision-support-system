import {
  aiInsightAssets,
  aiInsightDisclaimer,
  aiInsightHistoryLimit,
  aiInsightMockProfiles,
  analysisHorizons,
  defaultAIInsightConfig,
  investorObjectives,
  riskPreferences,
} from '../data/aiInsightsMockData'
import { forecastHorizonOptions } from '../data/predictionMockData'
import { suggestedActionExplanations } from '../utils/aiInsightActions'

const confidenceLevels = ['Low', 'Medium', 'High']
const riskLevels = ['Low', 'Moderate', 'High']

function findOption(options, id) {
  return options.find((option) => option.id === id) ?? options[0]
}

function hashString(value) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max)
}

export function sanitizePredictionContext(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null

  const rawSymbol = typeof value.asset === 'string' ? value.asset : value.asset?.symbol
  const symbol = typeof rawSymbol === 'string' ? rawSymbol.trim().toUpperCase() : ''
  const predictedDirection = typeof value.predictedDirection === 'string'
    ? value.predictedDirection.trim()
    : ''

  if (!symbol || !predictedDirection) return null

  const knownAsset = aiInsightAssets.find((asset) => asset.symbol === symbol)
  const asset = typeof value.asset === 'object'
    ? { ...knownAsset, ...value.asset, symbol }
    : knownAsset ?? { symbol, name: symbol, type: value.assetType ?? 'Unknown' }
  const id = value.id ?? value.forecastId ?? `prediction-${symbol}`
  const volatility = value.volatility ?? value.expectedVolatility

  return JSON.parse(JSON.stringify({
    ...value,
    id,
    forecastId: value.forecastId ?? id,
    asset,
    assetType: value.assetType ?? asset.type,
    predictedDirection,
    forecastHorizon: value.forecastHorizon ?? value.configuration?.horizon,
    volatility,
    expectedVolatility: value.expectedVolatility ?? volatility,
  }))
}

function normalizeConfig(config = {}) {
  const merged = { ...defaultAIInsightConfig, ...config }
  const asset = aiInsightAssets.find((item) => item.symbol === merged.symbol) ?? aiInsightAssets[0]
  const horizon = findOption(analysisHorizons, merged.horizon)
  const objective = findOption(investorObjectives, merged.objective)
  const riskPreference = findOption(riskPreferences, merged.riskPreference)

  return {
    symbol: asset.symbol,
    horizon: horizon.id,
    objective: objective.id,
    riskPreference: riskPreference.id,
    includePortfolio: Boolean(merged.includePortfolio),
    includeBacktest: Boolean(merged.includeBacktest),
    includePrediction: Boolean(merged.includePrediction),
  }
}

function getPredictionHorizonLabel(context) {
  const savedHorizon = context.forecastHorizon ?? context.configuration?.horizon
  return forecastHorizonOptions.find((option) => option.value === savedHorizon)?.label
    ?? savedHorizon
    ?? 'Unknown horizon'
}

function getPredictionVolatility(context) {
  return context.volatility ?? context.expectedVolatility ?? null
}

function getPredictionAgreement(context) {
  return context.modelAgreement?.agreement ?? null
}

function displayPredictionValue(value) {
  return value === undefined || value === null || value === '' ? 'Not available' : String(value)
}

function getTechnicalDirection(profile) {
  const positiveCount = profile.technicalSignals.filter((signal) => signal.assessment === 'Positive').length
  const negativeCount = profile.technicalSignals.filter((signal) => signal.assessment === 'Negative').length

  if (positiveCount >= 3 && positiveCount > negativeCount) return 'Up'
  if (negativeCount >= 3 && negativeCount > positiveCount) return 'Down'
  return 'Neutral'
}

function createPredictionAssessment(config, profile, predictionContext) {
  const context = sanitizePredictionContext(predictionContext)
  const available = Boolean(context)
  const sameAsset = available && context.asset.symbol === config.symbol
  const applied = config.includePrediction && sameAsset
  const technicalDirection = getTechnicalDirection(profile)
  const direction = context?.predictedDirection ?? null
  const isDirectionalPrediction = direction === 'Up' || direction === 'Down'
  const relationship = !applied
    ? 'not-applied'
    : !isDirectionalPrediction || technicalDirection === 'Neutral'
      ? 'neutral'
      : direction === technicalDirection
        ? 'aligned'
        : 'conflict'
  const rangeLower = Number(context?.forecastRange?.lower)
  const rangeUpper = Number(context?.forecastRange?.upper)
  const currentPrice = Number(context?.currentPrice)
  const hasUsableRange = Number.isFinite(rangeLower)
    && Number.isFinite(rangeUpper)
    && Number.isFinite(currentPrice)
    && currentPrice > 0
  const rangeWidthRatio = hasUsableRange ? (rangeUpper - rangeLower) / currentPrice : 0
  const volatility = getPredictionVolatility(context ?? {})
  const elevatedVolatility = volatility === 'Elevated' || volatility === 'High'
  const wideRange = rangeWidthRatio >= 0.08
  const agreement = context ? getPredictionAgreement(context) : null
  const hasReliabilityInputs = confidenceLevels.includes(context?.confidence)
    && ['Strong', 'Moderate', 'Weak'].includes(agreement)
  const reliability = !applied
    ? 'Low'
    : !hasReliabilityInputs
      ? 'Low'
      : context.confidence === 'High' && agreement === 'Strong' && !wideRange
      ? 'High'
      : context.confidence === 'Low' || agreement === 'Weak'
        ? 'Low'
        : 'Medium'

  return {
    context,
    available,
    sameAsset,
    applied,
    direction,
    technicalDirection,
    relationship,
    wideRange,
    elevatedVolatility,
    volatility,
    agreement,
    reliability,
  }
}

function formatSignedPercent(value) {
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`
}

function formatCurrency(value) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
  }).format(value)
}

function createPredictionEvidence(config, assessment) {
  if (!assessment.available) {
    return {
      included: false,
      status: 'unavailable',
      metrics: [],
      explanation: 'No forecast context is currently available.',
    }
  }

  const context = assessment.context
  const volatility = assessment.volatility
  const agreement = assessment.agreement
  const directionPhrase = context.predictedDirection === 'Up'
    ? 'a moderately positive direction'
    : context.predictedDirection === 'Down'
      ? 'a moderately negative direction'
      : 'a neutral direction'
  const uncertaintySignals = []
  if (assessment.elevatedVolatility) uncertaintySignals.push(`${volatility.toLowerCase()} volatility`)
  if (agreement && agreement !== 'Strong') uncertaintySignals.push(`${agreement.toLowerCase()} forecast consistency`)
  const uncertaintyPhrase = uncertaintySignals.length
    ? `but ${uncertaintySignals.join(' and ')} limit certainty.`
    : volatility && agreement
      ? 'with comparatively supportive reliability signals.'
      : 'while optional reliability details are not available in the saved context.'
  const probabilityValue = Number.isFinite(context.probabilityIncrease)
    ? `${context.probabilityIncrease}%`
    : 'Not available'
  const expectedReturnValue = Number.isFinite(context.expectedReturn)
    ? formatSignedPercent(context.expectedReturn)
    : 'Not available'
  const hasForecastRange = Number.isFinite(context.forecastRange?.lower)
    && Number.isFinite(context.forecastRange?.upper)
  const forecastRangeValue = hasForecastRange
    ? `${formatCurrency(context.forecastRange.lower)} - ${formatCurrency(context.forecastRange.upper)}`
    : 'Not available'
  const generatedDateValue = Number.isFinite(Date.parse(context.generatedAt))
    ? new Intl.DateTimeFormat('en-US', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      }).format(new Date(context.generatedAt))
    : 'Not available'
  const metrics = [
    { label: 'Asset', value: context.asset.symbol },
    { label: 'Forecast Horizon', value: getPredictionHorizonLabel(context) },
    { label: 'Predicted Direction', value: context.predictedDirection },
    { label: 'Probability of Increase', value: probabilityValue },
    { label: 'Expected Return', value: expectedReturnValue },
    { label: 'Forecast Confidence', value: displayPredictionValue(context.confidence) },
    { label: 'Forecast Range', value: forecastRangeValue },
    { label: 'Generated Date', value: generatedDateValue },
  ]

  if (!assessment.sameAsset) {
    return {
      included: false,
      status: 'mismatch',
      assetSymbol: context.asset.symbol,
      metrics,
      explanation: `The latest forecast is for ${context.asset.symbol} and was not applied to the current ${config.symbol} analysis.`,
    }
  }

  if (!config.includePrediction) {
    return {
      included: false,
      status: 'excluded',
      metrics,
      explanation: 'This forecast is available but was not included in the current analysis.',
    }
  }

  return {
    included: true,
    status: 'included',
    metrics,
    explanation: `The latest demo forecast indicates ${directionPhrase}, ${uncertaintyPhrase}`,
  }
}

export function createPredictionEvidenceFromContext(inputConfig, predictionContext) {
  const config = normalizeConfig(inputConfig)
  const profile = aiInsightMockProfiles[config.symbol] ?? aiInsightMockProfiles.AAPL
  const assessment = createPredictionAssessment(config, profile, predictionContext)
  return createPredictionEvidence(config, assessment)
}

function createFactor(id, title, description, tone = 'neutral', icon = 'check') {
  return { id, title, description, tone, icon }
}

function levelFromScore(score) {
  if (score >= 4) return confidenceLevels[2]
  if (score >= 2) return confidenceLevels[1]
  return confidenceLevels[0]
}

function riskLevelFromPoints(points) {
  if (points >= 5) return riskLevels[2]
  if (points >= 2) return riskLevels[1]
  return riskLevels[0]
}

function hasCurrentPosition(profile) {
  const positionValue = Number(String(profile.portfolioContext.currentPosition).replace(/[^0-9.-]/g, ''))
  return Number.isFinite(positionValue) && positionValue > 0
}

function getSuggestedAction({
  riskPoints,
  confidenceScore,
  config,
  profile,
  supportingFactors,
  predictionAssessment,
}) {
  const portfolioKnown = config.includePortfolio
  const currentlyHeld = portfolioKnown && hasCurrentPosition(profile)
  const portfolioWeight = portfolioKnown ? profile.portfolioContext.portfolioWeight : 0
  const highPortfolioWeight = portfolioKnown && portfolioWeight >= 30
  const technicalSignalsArePositive = profile.technicalState.trend === 'Bullish'
    && profile.technicalState.macd.includes('Positive')
    && profile.technicalState.priceVsMa20 === 'Above'
  const technicalDirectionIsUnclear = profile.technicalState.trend === 'Neutral'
    || profile.technicalState.macd.includes('Mixed')
  const supportiveMarketSignals = profile.marketContext.filter((item) => item.assessment === 'Positive').length
  const negativeMarketSignals = profile.marketContext.filter((item) => item.assessment === 'Negative').length
  const marketSignalsAreSupportive = supportiveMarketSignals >= 2 && negativeMarketSignals <= 1
  const predictionSupportsTrend = predictionAssessment.applied
    && predictionAssessment.direction === 'Up'
    && predictionAssessment.relationship === 'aligned'
    && ['High', 'Medium'].includes(predictionAssessment.context.confidence)
    && ['Strong', 'Moderate'].includes(predictionAssessment.agreement)
  const predictionIsWeak = predictionAssessment.applied
    && (
      predictionAssessment.direction === 'Down'
      || predictionAssessment.relationship === 'conflict'
      || predictionAssessment.context.confidence === 'Low'
      || predictionAssessment.agreement === 'Weak'
    )
  const cautiousPreference = config.riskPreference === 'conservative' || config.objective === 'risk-control'
  const riskIsClearlyElevated = riskPoints >= 6
    || (profile.technicalState.volatility === 'High' && riskPoints >= 4)
  const confidenceIsInsufficient = confidenceScore < 4
  const positiveEvidence = supportingFactors.length >= 3 && technicalSignalsArePositive
  const alignedEvidence = positiveEvidence && marketSignalsAreSupportive && predictionSupportsTrend
  const riskIsControlled = riskPoints <= (config.riskPreference === 'aggressive' ? 4 : 3)

  if (currentlyHeld && (riskIsClearlyElevated || predictionIsWeak)) {
    return 'Consider Reducing Exposure'
  }
  if (highPortfolioWeight) return 'Avoid Increasing Exposure'
  if (predictionIsWeak) return portfolioKnown && !currentlyHeld ? 'Wait Before Entering' : 'Monitor Closely'
  if (technicalDirectionIsUnclear || (predictionAssessment.applied && predictionAssessment.direction === 'Neutral')) {
    return 'Monitor Closely'
  }
  if (
    alignedEvidence
    && riskIsControlled
    && !cautiousPreference
    && confidenceScore >= 4
    && (!currentlyHeld || portfolioWeight < 25)
  ) {
    return 'Consider a Gradual Entry'
  }
  if (positiveEvidence && confidenceIsInsufficient) {
    if (currentlyHeld) return 'Hold and Monitor'
    if (portfolioKnown) return 'Wait Before Entering'
    return 'Monitor Closely'
  }
  if (currentlyHeld && positiveEvidence) return 'Hold and Monitor'
  if (portfolioKnown && !currentlyHeld) return 'Wait Before Entering'
  return 'Monitor Closely'
}

function getMarketBias(profile, riskPoints) {
  if (riskPoints >= 6 && profile.marketBiasBase.includes('Bullish')) return 'Neutral'
  return profile.marketBiasBase
}

function buildPredictionSummary(config, assessment) {
  if (!assessment.available) {
    return 'No prediction context was available, so the decision does not use forecast evidence.'
  }
  if (!config.includePrediction) {
    return 'Prediction context was not included, so the decision relies on the other selected evidence sources.'
  }
  if (!assessment.sameAsset) {
    return `The latest ${assessment.context.asset.symbol} demo prediction was not applied to the current ${config.symbol} analysis because the assets do not match.`
  }

  const context = assessment.context
  const horizonLabel = getPredictionHorizonLabel(context).toLowerCase()
  const volatility = assessment.volatility?.toLowerCase()
  const agreement = assessment.agreement?.toLowerCase()
  const limitationSignals = [
    volatility ? `${volatility} volatility` : null,
    agreement ? `${agreement} forecast consistency` : null,
  ].filter(Boolean)
  const limitations = limitationSignals.length
    ? `although ${limitationSignals.join(' and ')} limit certainty.`
    : 'while optional reliability details are unavailable.'
  if (assessment.relationship === 'conflict') {
    return `The latest ${horizonLabel} demo forecast points ${context.predictedDirection.toLowerCase()} while current technical indicators point ${assessment.technicalDirection.toLowerCase()}. This disagreement reduces confidence and supports waiting for further confirmation.`
  }
  if (context.predictedDirection === 'Neutral') {
    return `The latest ${horizonLabel} demo forecast is neutral. It adds uncertainty rather than a strong directional recommendation.`
  }
  if (assessment.relationship === 'aligned') {
    const directionProbability = Number.isFinite(context.probabilityIncrease)
      ? context.predictedDirection === 'Up'
        ? `${context.probabilityIncrease}% probability to an upward move`
        : `${100 - context.probabilityIncrease}% probability to a non-increasing outcome`
      : `${context.predictedDirection.toLowerCase()} direction`
    return `The latest ${horizonLabel} demo forecast assigns a ${directionProbability}. This broadly supports the current technical direction, ${limitations}`
  }
  const confidencePhrase = context.confidence
    ? ` with ${String(context.confidence).toLowerCase()} confidence`
    : ''
  return `The latest ${horizonLabel} demo forecast points ${context.predictedDirection.toLowerCase()}${confidencePhrase}. It is treated as limited supporting evidence rather than a direct trade signal.`
}

function buildSummary({
  asset,
  config,
  profile,
  horizon,
  objective,
  riskPreference,
  suggestedAction,
  suggestedActionExplanation,
  predictionAssessment,
}) {
  const { technicalState } = profile
  const parts = []

  if (config.horizon === 'short-term') {
    parts.push(`${asset.symbol}'s short-term setup prioritises RSI at ${technicalState.rsi.toFixed(1)}, ${technicalState.macd.toLowerCase()}, and ${technicalState.volatility.toLowerCase()} volatility. Price is trading ${technicalState.priceVsMa20.toLowerCase()} MA20.`)
    parts.push(technicalState.rsi >= 65
      ? 'Near-term momentum is extended enough to require confirmation before increasing conviction.'
      : 'Near-term momentum is not extended, which keeps the technical setup balanced.')
  } else if (config.horizon === 'long-term') {
    parts.push(`${asset.symbol}'s long-term view prioritises its ${technicalState.trend.toLowerCase()} trend and ${technicalState.volatility.toLowerCase()} volatility as indicators of risk stability. Price remains ${technicalState.priceVsMa20.toLowerCase()} MA20.`)
    parts.push(technicalState.rsi >= 65
      ? 'RSI is elevated, but it is treated as a secondary timing warning within the longer-term view.'
      : 'RSI is not extended and remains a secondary timing input within the longer-term view.')
  } else {
    parts.push(`${asset.symbol} remains ${technicalState.trend.toLowerCase()} on a ${horizon.phrase} basis, with ${technicalState.macd.toLowerCase()} and price trading ${technicalState.priceVsMa20.toLowerCase()} MA20.`)
    parts.push(technicalState.rsi >= 65
      ? `However, RSI is approaching an elevated level and ${technicalState.volatility.toLowerCase()} volatility reduces entry timing quality.`
      : 'RSI is not extended, which keeps the technical setup balanced.')
  }

  parts.push(buildPredictionSummary(config, predictionAssessment))

  if (config.objective === 'capital-growth') {
    parts.push('The capital growth objective gives greater weight to trend, momentum, and relative strength.')
  } else if (config.objective === 'risk-control') {
    const backtestRisk = config.includeBacktest
      ? `the ${profile.backtestEvidence.maximumDrawdownLabel} backtest drawdown`
      : 'drawdown tolerance'
    const portfolioRisk = config.includePortfolio
      ? `, ${profile.portfolioContext.portfolioWeightLabel} portfolio concentration, and ${profile.portfolioContext.availableLiquidity} available liquidity`
      : ''
    parts.push(`The risk control objective gives greater weight to ${technicalState.volatility.toLowerCase()} volatility, ${backtestRisk}${portfolioRisk}.`)
  } else {
    parts.push('The balanced growth objective weighs growth potential against volatility, drawdown, and position sizing.')
  }

  if (config.includeBacktest) {
    parts.push(`The latest ${profile.backtestEvidence.strategy.toLowerCase()} backtest outperformed the benchmark, while its Sharpe ratio of ${profile.backtestEvidence.sharpeRatio.toFixed(2)} keeps the evidence ${profile.backtestEvidence.sharpeRatio >= 1 ? 'supportive' : 'moderate'}.`)
  } else {
    parts.push('Backtest evidence was excluded, so the conclusion relies more heavily on current technical and market context.')
  }

  if (config.includePortfolio) {
    parts.push(`Portfolio exposure is ${profile.portfolioContext.portfolioWeightLabel} and remains part of the sizing assessment.`)
  } else {
    parts.push('Portfolio exposure was not included, so position sizing risk should be reviewed separately before acting.')
  }

  const riskScope = config.includePortfolio
    ? 'volatility and concentration risk'
    : 'volatility and drawdown risk'
  if (config.riskPreference === 'conservative') {
    parts.push(`The conservative preference requires stronger confirmation before accepting ${riskScope}.`)
  } else if (config.riskPreference === 'aggressive') {
    const retainedWarnings = config.includePortfolio
      ? 'concentration and drawdown warnings remain in force'
      : 'drawdown warnings remain in force'
    parts.push(`The aggressive preference accepts more volatility, but ${retainedWarnings}.`)
  } else {
    parts.push(`The moderate preference balances upside participation against ${riskScope}.`)
  }

  parts.push(`Suggested action: ${suggestedAction}. ${suggestedActionExplanation} This is decision support, not an instruction to place a trade.`)

  return parts.join(' ')
}

function createEvidenceMetrics(profile, includePortfolio, includeBacktest) {
  const portfolioContext = includePortfolio
    ? {
        included: true,
        metrics: [
          { label: 'Current Position', value: profile.portfolioContext.currentPosition },
          { label: 'Portfolio Weight', value: profile.portfolioContext.portfolioWeightLabel },
          { label: 'Unrealised Return', value: profile.portfolioContext.unrealisedReturn },
          { label: 'Concentration Risk', value: profile.portfolioContext.concentrationRisk },
          { label: 'Available Liquidity', value: profile.portfolioContext.availableLiquidity },
        ],
        explanation: profile.portfolioContext.explanation,
      }
    : {
        included: false,
        metrics: [],
        explanation: 'Portfolio context was not included in this analysis.',
      }

  const backtestEvidence = includeBacktest
    ? {
        included: true,
        metrics: [
          { label: 'Strategy', value: profile.backtestEvidence.strategy },
          { label: 'Total Return', value: profile.backtestEvidence.totalReturnLabel },
          { label: 'Benchmark Return', value: profile.backtestEvidence.benchmarkReturnLabel },
          { label: 'Maximum Drawdown', value: profile.backtestEvidence.maximumDrawdownLabel },
          { label: 'Sharpe Ratio', value: profile.backtestEvidence.sharpeRatio.toFixed(2) },
          { label: 'Number of Trades', value: String(profile.backtestEvidence.numberOfTrades) },
        ],
        explanation: profile.backtestEvidence.explanation,
      }
    : {
        included: false,
        metrics: [],
        explanation: 'Backtest evidence was not included in this analysis.',
      }

  return { portfolioContext, backtestEvidence }
}

function createRecommendedNextSteps({
  config,
  profile,
  suggestedAction,
  suggestedActionExplanation,
  predictionAssessment,
}) {
  const steps = [suggestedActionExplanation]

  if (config.horizon === 'short-term') {
    steps.push(profile.technicalState.rsi >= 65
      ? 'Wait for short-term confirmation from RSI or MACD before increasing exposure.'
      : 'Confirm RSI, MACD, and recent volatility before changing near-term exposure.')
  } else if (config.horizon === 'long-term') {
    const portfolioFocus = config.includePortfolio ? ', portfolio concentration,' : ''
    steps.push(`Review whether the long-term trend${portfolioFocus} and risk stability remain intact before changing exposure.`)
  } else {
    steps.push(config.includeBacktest
      ? 'Confirm that the medium-term trend remains aligned with backtest and market context.'
      : 'Confirm that the medium-term trend remains aligned with current market context.')
  }

  if (predictionAssessment.applied) {
    steps.push('Review whether the latest prediction agrees with current technical signals.')
    if (predictionAssessment.wideRange || predictionAssessment.elevatedVolatility) {
      steps.push('Re-run the forecast if market volatility changes materially.')
    }
    if (predictionAssessment.agreement === 'Weak') {
      steps.push('Compare the prediction with a different forecast horizon.')
    }
    const predictionConfidence = predictionAssessment.context.confidence
    if (predictionConfidence !== 'High') {
      const confidenceLabel = predictionConfidence
        ? `${String(predictionConfidence).toLowerCase()}-confidence`
        : 'limited-context'
      steps.push(`Avoid treating a ${confidenceLabel} forecast as a direct trade signal.`)
    }
  }

  const riskPreferenceStep = config.riskPreference === 'conservative'
    ? 'Apply a higher confirmation threshold for the conservative preference.'
    : config.riskPreference === 'aggressive'
      ? `The aggressive preference accepts more volatility, but ${config.includePortfolio ? 'concentration and drawdown limits' : 'drawdown limits'} still apply.`
      : 'Keep supporting and risk evidence balanced for the moderate preference.'
  if (config.objective === 'capital-growth') {
    steps.push(`Compare trend, momentum, and relative strength before raising conviction. ${riskPreferenceStep}`)
  } else if (config.objective === 'risk-control') {
    const portfolioControls = config.includePortfolio ? ', concentration risk, and available liquidity' : ''
    steps.push(`Prioritise volatility, drawdown${portfolioControls} before changing exposure. ${riskPreferenceStep}`)
  } else {
    steps.push(`Balance growth potential against volatility, drawdown, and position size. ${riskPreferenceStep}`)
  }

  if (config.includePortfolio) {
    if (profile.portfolioContext.portfolioWeight >= 25) {
      steps.push('Avoid increasing the asset above the selected portfolio concentration limit.')
    } else {
      steps.push('Check whether portfolio sizing remains aligned with the selected risk preference.')
    }
  }

  steps.push('Review the latest support level in Market Analysis.')

  if (config.includeBacktest) {
    steps.push('Compare the result with a longer backtest period before raising conviction.')
  } else {
    steps.push('Run or review a backtest before treating this insight as strongly supported.')
  }

  if (profile.technicalState.volatility === 'Elevated' || profile.technicalState.volatility === 'High') {
    steps.push('Reassess if volatility continues to increase.')
  } else if (suggestedAction === 'Consider a Gradual Entry') {
    steps.push('Confirm that liquidity and drawdown tolerance remain acceptable before adding exposure.')
  } else {
    steps.push('Reassess the setup after the next market data update.')
  }

  return steps
}

function createConfidenceExplanation({
  confidence,
  config,
  profile,
  supportCount,
  riskCount,
  predictionAssessment,
}) {
  const hasCompleteContext = config.includePortfolio
    && config.includeBacktest
    && (!config.includePrediction || predictionAssessment.applied)
  const technicalSignalsByKey = Object.fromEntries(
    profile.technicalSignals.map((signal) => [signal.key, signal]),
  )
  const shortTermSignals = ['rsi', 'macd', 'volatility']
    .map((key) => technicalSignalsByKey[key])
    .filter(Boolean)
  const technicalSignalAgreement = config.horizon === 'short-term'
    ? shortTermSignals.filter((signal) => signal.assessment === 'Positive').length >= 2
      && shortTermSignals.every((signal) => signal.assessment !== 'Negative')
    : config.horizon === 'long-term'
      ? technicalSignalsByKey.trend?.assessment === 'Positive'
        && profile.technicalState.volatility !== 'High'
        && (!config.includePortfolio || profile.portfolioContext.portfolioWeight < 30)
      : profile.technicalSignals.filter((signal) => signal.assessment === 'Positive').length >= 3
  const crossSignalLevel = predictionAssessment.applied
    ? predictionAssessment.relationship === 'aligned'
      ? 'High'
      : predictionAssessment.relationship === 'conflict'
        ? 'Low'
        : 'Medium'
    : technicalSignalAgreement ? 'High' : 'Medium'
  const predictionRelevanceDetail = predictionAssessment.applied
    ? `The ${predictionAssessment.context.asset.symbol} forecast matches the selected asset.`
    : predictionAssessment.available && !predictionAssessment.sameAsset
      ? `The ${predictionAssessment.context.asset.symbol} forecast was not applied to ${config.symbol}.`
      : predictionAssessment.available
        ? 'Prediction context was intentionally excluded.'
        : 'No valid prediction context is available.'
  const predictionReliabilityLevel = predictionAssessment.applied
    ? predictionAssessment.reliability
    : 'Low'
  const backtestReliable = config.includeBacktest
    && profile.backtestEvidence.sharpeRatio >= 1
    && profile.backtestEvidence.numberOfTrades >= 10
  const portfolioRelevant = config.includePortfolio && profile.portfolioContext.portfolioWeight < 30
  const marketUncertainty = profile.technicalState.volatility === 'High'
    ? 'High'
    : profile.technicalState.volatility === 'Elevated'
      ? 'Medium'
      : 'Low'
  const horizonRationale = config.horizon === 'short-term'
    ? 'The short-term view gives extra weight to RSI, MACD, and volatility.'
    : config.horizon === 'long-term'
      ? `The long-term view gives extra weight to trend persistence, risk stability${config.includePortfolio ? ', and portfolio exposure' : ''}.`
      : `The medium-term view balances technical trend${config.includeBacktest ? ' with backtest evidence' : ' with current market context'}.`
  const riskPreferenceRationale = config.riskPreference === 'conservative'
    ? 'The conservative preference requires stronger evidence before conviction increases.'
    : config.riskPreference === 'aggressive'
      ? `The aggressive preference accepts more volatility, but ${config.includePortfolio ? 'concentration and drawdown warnings' : 'drawdown warnings'} remain active.`
      : 'The moderate preference keeps supporting and risk evidence balanced.'

  return {
    body: `Confidence is rated ${confidence} because ${supportCount} supporting signals are balanced against ${riskCount} risk warnings, with ${hasCompleteContext ? 'the selected context inputs included' : 'one or more selected context inputs unavailable or excluded'}. ${horizonRationale} ${riskPreferenceRationale}`,
    factors: [
      {
        label: 'Data completeness',
        level: hasCompleteContext ? 'High' : 'Medium',
        tone: hasCompleteContext ? 'positive' : 'neutral',
        detail: hasCompleteContext ? 'All selected evidence inputs are available.' : 'A selected context input is unavailable or excluded.',
      },
      {
        label: 'Cross-signal agreement',
        level: crossSignalLevel,
        tone: crossSignalLevel === 'High' ? 'positive' : crossSignalLevel === 'Low' ? 'negative' : 'neutral',
        detail: predictionAssessment.applied
          ? predictionAssessment.relationship === 'aligned'
            ? 'The latest demo prediction agrees with the current technical direction.'
            : predictionAssessment.relationship === 'conflict'
              ? 'The latest demo prediction conflicts with the current technical direction.'
              : 'The prediction or technical setup is directionally neutral.'
          : config.horizon === 'short-term'
            ? 'Technical agreement emphasises RSI, MACD, and volatility.'
            : config.horizon === 'long-term'
              ? 'Technical agreement emphasises trend persistence and volatility stability.'
              : technicalSignalAgreement
                ? 'Trend and momentum signals mostly point in the same direction.'
                : 'Trend and momentum signals are mixed.',
      },
      {
        label: 'Backtest reliability',
        level: backtestReliable ? 'High' : config.includeBacktest ? 'Medium' : 'Low',
        tone: backtestReliable ? 'positive' : config.includeBacktest ? 'warning' : 'negative',
        detail: config.includeBacktest ? 'Reliability reflects Sharpe ratio and trade sample size.' : 'Backtest evidence was excluded.',
      },
      {
        label: 'Portfolio relevance',
        level: portfolioRelevant ? 'High' : config.includePortfolio ? 'Medium' : 'Low',
        tone: portfolioRelevant ? 'positive' : config.includePortfolio ? 'warning' : 'negative',
        detail: config.includePortfolio ? 'Sizing context was considered.' : 'Portfolio context was excluded.',
      },
      {
        label: 'Market uncertainty',
        level: marketUncertainty,
        tone: marketUncertainty === 'Low' ? 'positive' : marketUncertainty === 'Medium' ? 'warning' : 'negative',
        detail: `Volatility regime is ${profile.technicalState.volatility.toLowerCase()}.`,
      },
      {
        label: 'Prediction relevance',
        level: predictionAssessment.applied ? 'High' : 'Low',
        tone: predictionAssessment.applied ? 'positive' : 'negative',
        detail: predictionRelevanceDetail,
      },
      {
        label: 'Prediction reliability',
        level: predictionReliabilityLevel,
        tone: predictionReliabilityLevel === 'High' ? 'positive' : predictionReliabilityLevel === 'Medium' ? 'warning' : 'negative',
        detail: predictionAssessment.applied
          ? `${displayPredictionValue(predictionAssessment.context.confidence)} forecast confidence with ${displayPredictionValue(predictionAssessment.agreement).toLowerCase()} forecast consistency.`
          : 'Prediction reliability was not used in this analysis.',
      },
    ],
  }
}

function orderFactorsForHorizon(factors, horizon) {
  const priorities = {
    'short-term': ['elevated-rsi', 'volatility', 'technical-trend', 'price-ma20', 'relative-strength', 'portfolio-concentration', 'portfolio-capacity', 'backtest-return', 'moderate-sharpe', 'limited-trades'],
    'medium-term': ['technical-trend', 'price-ma20', 'backtest-return', 'moderate-sharpe', 'limited-trades', 'elevated-rsi', 'volatility', 'portfolio-concentration', 'portfolio-capacity', 'relative-strength'],
    'long-term': ['technical-trend', 'portfolio-concentration', 'portfolio-capacity', 'volatility', 'backtest-return', 'moderate-sharpe', 'limited-trades', 'relative-strength', 'price-ma20', 'elevated-rsi'],
  }
  const order = priorities[horizon] ?? priorities['medium-term']

  return [...factors].sort((left, right) => {
    const leftIndex = order.indexOf(left.id)
    const rightIndex = order.indexOf(right.id)
    return (leftIndex === -1 ? order.length : leftIndex) - (rightIndex === -1 ? order.length : rightIndex)
  })
}

export function generateMockAIInsight(inputConfig, generatedAt = new Date(), predictionContext = null) {
  const config = normalizeConfig(inputConfig)
  const asset = aiInsightAssets.find((item) => item.symbol === config.symbol) ?? aiInsightAssets[0]
  const profile = aiInsightMockProfiles[asset.symbol] ?? aiInsightMockProfiles.AAPL
  const horizon = findOption(analysisHorizons, config.horizon)
  const objective = findOption(investorObjectives, config.objective)
  const riskPreference = findOption(riskPreferences, config.riskPreference)

  const supportingFactors = []
  const riskFactors = []
  const predictionAssessment = createPredictionAssessment(config, profile, predictionContext)
  let confidenceScore = 5
  let riskPoints = 1

  if (profile.technicalState.trend === 'Bullish' && profile.technicalState.macd.includes('Positive')) {
    supportingFactors.push(createFactor(
      'technical-trend',
      'Technical trend is constructive',
      'Price remains above key moving averages while MACD momentum is positive.',
      'positive',
      'trend',
    ))
  }

  if (profile.technicalState.priceVsMa20 === 'Above') {
    supportingFactors.push(createFactor(
      'price-ma20',
      'Price remains above MA20',
      'The latest price is holding above the 20-period moving average.',
      'positive',
      'check',
    ))
  }

  if (profile.technicalState.rsi >= 65) {
    riskFactors.push(createFactor(
      'elevated-rsi',
      'RSI is approaching an elevated level',
      'Momentum is positive, but the entry point may be less attractive without confirmation.',
      'warning',
      'alert',
    ))
    confidenceScore -= 1
    riskPoints += 1
  }

  if (profile.technicalState.volatility === 'Elevated' || profile.technicalState.volatility === 'High') {
    riskFactors.push(createFactor(
      'volatility',
      'Recent volatility has increased',
      'Higher volatility can widen drawdowns and reduce the reliability of a near-term signal.',
      profile.technicalState.volatility === 'High' ? 'negative' : 'warning',
      'shield',
    ))
    riskPoints += profile.technicalState.volatility === 'High' ? 2 : 1
  }

  if (config.includePortfolio) {
    if (profile.portfolioContext.portfolioWeight >= 30) {
      riskFactors.push(createFactor(
        'portfolio-concentration',
        'Portfolio concentration is already high',
        `${asset.symbol} represents ${profile.portfolioContext.portfolioWeightLabel} of the demo portfolio.`,
        'warning',
        'portfolio',
      ))
      confidenceScore -= 1
      riskPoints += 1
    } else {
      supportingFactors.push(createFactor(
        'portfolio-capacity',
        'Portfolio concentration is manageable',
        `${asset.symbol} exposure is below the mock concentration threshold.`,
        'positive',
        'portfolio',
      ))
    }
  } else {
    riskFactors.push(createFactor(
      'portfolio-excluded',
      'Portfolio exposure was not included',
      'Position sizing should be reviewed separately before using the insight.',
      'neutral',
      'portfolio',
    ))
    confidenceScore -= 1
  }

  if (config.includeBacktest) {
    if (profile.backtestEvidence.totalReturn > profile.backtestEvidence.benchmarkReturn) {
      supportingFactors.push(createFactor(
        'backtest-return',
        'Backtest return exceeded the benchmark',
        `${profile.backtestEvidence.strategy} returned ${profile.backtestEvidence.totalReturnLabel} versus ${profile.backtestEvidence.benchmarkReturnLabel} for the benchmark.`,
        'positive',
        'strategy',
      ))
    }

    if (profile.backtestEvidence.sharpeRatio < 1) {
      riskFactors.push(createFactor(
        'moderate-sharpe',
        'Backtest Sharpe ratio is moderate',
        `The Sharpe ratio is ${profile.backtestEvidence.sharpeRatio.toFixed(2)}, so risk-adjusted evidence is positive but limited.`,
        'warning',
        'alert',
      ))
      confidenceScore -= 1
    } else {
      confidenceScore += 1
    }

    if (profile.backtestEvidence.numberOfTrades < 10) {
      riskFactors.push(createFactor(
        'limited-trades',
        'Backtest sample is limited',
        `The current mock sample contains only ${profile.backtestEvidence.numberOfTrades} trades.`,
        'warning',
        'history',
      ))
    }
  } else {
    riskFactors.push(createFactor(
      'backtest-excluded',
      'Backtest evidence was not included',
      'The insight does not use the latest strategy evidence for this configuration.',
      'neutral',
      'strategy',
    ))
    confidenceScore -= 1
  }

  if (profile.marketContext.some((item) => item.value.includes('Above') || item.value.includes('Leading'))) {
    supportingFactors.push(createFactor(
      'relative-strength',
      'Relative strength is supportive',
      'The selected asset is stronger than the broad market in the current mock context.',
      'positive',
      'market',
    ))
  }

  if (predictionAssessment.applied) {
    const context = predictionAssessment.context
    const probabilityIncrease = Number.isFinite(context.probabilityIncrease)
      ? context.probabilityIncrease
      : null

    if (context.predictedDirection === 'Up') {
      if (predictionAssessment.relationship === 'conflict') {
        riskFactors.push(createFactor(
          'prediction-conflict',
          'Prediction conflicts with the technical direction',
          `The latest demo forecast points upward while the current technical direction is ${predictionAssessment.technicalDirection.toLowerCase()}.`,
          'warning',
          'prediction',
        ))
        confidenceScore -= 1
        riskPoints += 1
      } else {
        supportingFactors.push(createFactor(
          'prediction-support',
          predictionAssessment.relationship === 'aligned'
            ? 'Prediction direction supports the technical trend'
            : 'Prediction offers limited directional support',
          probabilityIncrease === null
            ? 'The latest demo forecast points upward, but its probability was not saved.'
            : `The latest demo forecast assigns a ${probabilityIncrease}% probability to an upward move.`,
          context.confidence === 'High' ? 'positive' : 'neutral',
          'prediction',
        ))
        if (predictionAssessment.relationship === 'aligned') confidenceScore += 1
        if (probabilityIncrease >= 65 && context.confidence === 'High') confidenceScore += 1
      }
    } else if (context.predictedDirection === 'Down') {
      riskFactors.push(createFactor(
        'prediction-downside',
        'Latest prediction points downward',
        probabilityIncrease === null
          ? 'The latest demo forecast points downward, but its probability was not saved.'
          : `The latest demo forecast assigns a ${100 - probabilityIncrease}% probability to a non-increasing outcome.`,
        'negative',
        'prediction',
      ))
      riskPoints += 2
      if (predictionAssessment.relationship === 'conflict') confidenceScore -= 1
    } else {
      riskFactors.push(createFactor(
        'prediction-neutral',
        'Prediction remains directionally neutral',
        'The latest demo forecast does not provide a strong directional signal.',
        'neutral',
        'prediction',
      ))
      confidenceScore -= 1
    }

    if (predictionAssessment.agreement === 'Weak') confidenceScore -= 1
    if (predictionAssessment.wideRange || predictionAssessment.elevatedVolatility) {
      riskFactors.push(createFactor(
        'prediction-uncertainty',
        'Forecast uncertainty remains meaningful',
        `The forecast range is ${predictionAssessment.wideRange ? 'wide' : 'not narrow'} and forecast consistency is ${displayPredictionValue(predictionAssessment.agreement).toLowerCase()}.`,
        predictionAssessment.agreement === 'Weak' ? 'negative' : 'warning',
        'alert',
      ))
      confidenceScore -= 1
      riskPoints += 1
    }
  }

  if (config.objective === 'risk-control') riskPoints += 1
  if (config.riskPreference === 'conservative') riskPoints += 1
  confidenceScore = clamp(confidenceScore, 0, 5)
  const confidence = levelFromScore(confidenceScore)
  const riskLevel = riskLevelFromPoints(riskPoints)
  const suggestedAction = getSuggestedAction({
    riskPoints,
    confidenceScore,
    config,
    profile,
    supportingFactors,
    predictionAssessment,
  })
  const suggestedActionExplanation = suggestedActionExplanations[suggestedAction]
  const marketBias = getMarketBias(profile, riskPoints)
  const { portfolioContext, backtestEvidence } = createEvidenceMetrics(
    profile,
    config.includePortfolio,
    config.includeBacktest,
  )
  const confidenceExplanation = createConfidenceExplanation({
    confidence,
    config,
    profile,
    supportCount: supportingFactors.length,
    riskCount: riskFactors.length,
    predictionAssessment,
  })
  const orderedSupportingFactors = orderFactorsForHorizon(supportingFactors, config.horizon)
  const orderedRiskFactors = orderFactorsForHorizon(riskFactors, config.horizon)
  const predictionSignature = predictionAssessment.context
    ? `${predictionAssessment.context.forecastId}:${predictionAssessment.context.generatedAt}`
    : 'no-prediction'
  const id = `ai-insight-${hashString(JSON.stringify({ config, predictionSignature })).toString(36)}`
  const predictionEvidence = createPredictionEvidence(config, predictionAssessment)

  return {
    schemaVersion: 1,
    id,
    asset,
    configuration: {
      ...config,
      horizonLabel: horizon.label,
      objectiveLabel: objective.label,
      riskPreferenceLabel: riskPreference.label,
    },
    generatedAt: generatedAt.toISOString(),
    suggestedAction,
    suggestedActionExplanation,
    confidence,
    riskLevel,
    marketBias,
    summary: buildSummary({
      asset,
      config,
      profile,
      horizon,
      objective,
      riskPreference,
      suggestedAction,
      suggestedActionExplanation,
      predictionAssessment,
    }),
    technicalSignals: profile.technicalSignals,
    portfolioContext,
    backtestEvidence,
    predictionEvidence,
    predictionContext: predictionAssessment.applied ? predictionAssessment.context : null,
    marketContext: profile.marketContext,
    supportingFactors: orderedSupportingFactors,
    riskFactors: orderedRiskFactors,
    recommendedNextSteps: createRecommendedNextSteps({
      config,
      profile,
      suggestedAction,
      suggestedActionExplanation,
      predictionAssessment,
    }),
    confidenceExplanation,
    disclaimer: aiInsightDisclaimer,
  }
}

export function sanitizeAIInsightHistory(value) {
  if (!Array.isArray(value)) return []
  const knownSymbols = new Set(aiInsightAssets.map((asset) => asset.symbol))

  return [...value]
    .filter((insight) => (
      insight?.schemaVersion === 1
      && typeof insight.id === 'string'
      && Number.isFinite(Date.parse(insight.generatedAt))
      && typeof insight.asset?.symbol === 'string'
      && knownSymbols.has(insight.asset.symbol)
      && insight.configuration
      && typeof insight.suggestedAction === 'string'
      && typeof insight.confidence === 'string'
      && typeof insight.riskLevel === 'string'
      && typeof insight.summary === 'string'
      && Array.isArray(insight.technicalSignals)
      && Array.isArray(insight.marketContext)
      && Array.isArray(insight.supportingFactors)
      && Array.isArray(insight.riskFactors)
      && Array.isArray(insight.recommendedNextSteps)
      && insight.confidenceExplanation
    ))
    .sort((left, right) => Date.parse(right.generatedAt) - Date.parse(left.generatedAt))
    .slice(0, aiInsightHistoryLimit)
}
