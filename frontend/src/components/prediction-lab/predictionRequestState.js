export const QUALITY_GATE_UNAVAILABLE_MESSAGE = 'The selected model did not pass the complete two-stage quality gate, so no directional prediction is provided.'
export const REGRESSION_UNAVAILABLE_MESSAGE = 'The regression model did not pass the complete quality gate, so no expected return or predicted price is provided.'

export function clearPredictionResultForRequest() {
  return null
}

export function clearedPredictionViewState() {
  return {
    currentForecast: null,
    requestError: '',
    isLoading: false,
  }
}

export function failedPredictionViewState(error) {
  return {
    currentForecast: null,
    requestError: error?.message || 'Unable to load real market data.',
  }
}

export function predictionAssetChanged(currentAsset, nextAsset) {
  return currentAsset?.id !== nextAsset?.id
    || currentAsset?.symbol !== nextAsset?.symbol
    || currentAsset?.mic_code !== nextAsset?.mic_code
}

export function createLatestPredictionRequestGuard() {
  let latestRequestId = 0
  let active = true
  return {
    activate() {
      active = true
    },
    start() {
      latestRequestId += 1
      return latestRequestId
    },
    invalidate() {
      latestRequestId += 1
    },
    isCurrent(requestId) {
      return active && requestId === latestRequestId
    },
    dispose() {
      active = false
      latestRequestId += 1
    },
  }
}

export function updatePredictionConfiguration(configuration, field, value) {
  return { ...configuration, [field]: value }
}

export function buildPredictionRequestPayload(configuration, selectedAsset) {
  return {
    symbol: selectedAsset.symbol,
    classification_forecast_horizon: configuration.classificationForecastHorizon,
    regression_forecast_horizon: configuration.regressionForecastHorizon,
    lookback: configuration.lookback,
    security_selection: {
      id: selectedAsset.id,
      symbol: selectedAsset.symbol,
      name: selectedAsset.name,
      exchange: selectedAsset.exchange,
      mic_code: selectedAsset.mic_code,
      instrument_type: selectedAsset.instrument_type,
      country: selectedAsset.country,
      currency: selectedAsset.currency,
      search_query: selectedAsset.search_query || selectedAsset.symbol,
    },
  }
}

export function regressionPublicationState(response) {
  const available = response?.regression_prediction_available === true
  const expectedReturn = Number(response?.expected_return)
  const predictedPrice = Number(response?.predicted_price)
  return {
    available,
    expectedReturn: available
      && response?.expected_return != null
      && Number.isFinite(expectedReturn) ? expectedReturn : null,
    predictedPrice: available
      && response?.predicted_price != null
      && Number.isFinite(predictedPrice) ? predictedPrice : null,
    model: available ? response?.regression_model ?? null : null,
  }
}

export function predictionUnavailableMessage(response) {
  const qualityGateFailed = response?.prediction?.status === 'quality_gate_failed'
    || response?.prediction_quality_gate?.classification?.passed === false
  if (qualityGateFailed) {
    return response?.prediction?.message
      ?? response?.prediction_unavailable_reason
      ?? QUALITY_GATE_UNAVAILABLE_MESSAGE
  }
  return response?.prediction?.message
    ?? response?.prediction_unavailable_reason
    ?? 'Insufficient historical data for machine-learning prediction.'
}

export function regressionUnavailableMessage(response) {
  return response?.regression_prediction_unavailable_reason
    ?? response?.regression_prediction?.message
    ?? REGRESSION_UNAVAILABLE_MESSAGE
}
