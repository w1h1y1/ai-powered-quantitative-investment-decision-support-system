import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildPredictionRequestPayload,
  QUALITY_GATE_UNAVAILABLE_MESSAGE,
  REGRESSION_UNAVAILABLE_MESSAGE,
  clearedPredictionViewState,
  clearPredictionResultForRequest,
  createLatestPredictionRequestGuard,
  failedPredictionViewState,
  predictionAssetChanged,
  predictionUnavailableMessage,
  regressionUnavailableMessage,
  regressionPublicationState,
  updatePredictionConfiguration,
} from './predictionRequestState.js'
import {
  defaultPredictionConfig,
  directionHorizonOptions,
  predictionLookbackOptions,
  returnHorizonOptions,
} from '../../data/predictionConfig.js'

test('direction and return horizons have independent options and defaults', () => {
  assert.deepEqual(directionHorizonOptions.map((option) => option.value), [1, 5])
  assert.deepEqual(returnHorizonOptions.map((option) => option.value), [5, 10, 20])
  assert.equal(defaultPredictionConfig.classificationForecastHorizon, 1)
  assert.equal(defaultPredictionConfig.regressionForecastHorizon, 10)
  assert.equal(defaultPredictionConfig.lookback, 1260)
  assert.deepEqual(
    predictionLookbackOptions
      .filter((option) => [504, 756, 1260].includes(option.value))
      .map((option) => option.value),
    [504, 756, 1260],
  )
  assert.equal(Object.hasOwn(defaultPredictionConfig, 'horizon'), false)
})

test('updating either horizon does not overwrite the other horizon state', () => {
  const directionChanged = updatePredictionConfiguration(
    defaultPredictionConfig,
    'classificationForecastHorizon',
    5,
  )
  const returnChanged = updatePredictionConfiguration(
    directionChanged,
    'regressionForecastHorizon',
    20,
  )

  assert.equal(directionChanged.classificationForecastHorizon, 5)
  assert.equal(directionChanged.regressionForecastHorizon, 10)
  assert.equal(returnChanged.classificationForecastHorizon, 5)
  assert.equal(returnChanged.regressionForecastHorizon, 20)
})

test('prediction request sends both independent backend horizons without legacy horizon', () => {
  const payload = buildPredictionRequestPayload(
    {
      ...defaultPredictionConfig,
      classificationForecastHorizon: 5,
      regressionForecastHorizon: 20,
    },
    {
      id: 17,
      symbol: 'NVDA',
      name: 'NVIDIA Corporation',
      exchange: 'NASDAQ',
      mic_code: 'XNAS',
      instrument_type: 'Common Stock',
      country: 'United States',
      currency: 'USD',
      search_query: 'NVIDIA',
    },
  )

  assert.equal(payload.classification_forecast_horizon, 5)
  assert.equal(payload.regression_forecast_horizon, 20)
  assert.equal(payload.lookback, 1260)
  assert.equal(payload.security_selection.symbol, 'NVDA')
  assert.equal(Object.hasOwn(payload, 'horizon'), false)
  assert.equal(Object.hasOwn(payload, 'forecast_horizon'), false)
})

test('each historical lookback option is sent as its exact trading-day count', () => {
  const asset = {
    id: 3,
    symbol: 'AAPL',
    name: 'Apple Inc.',
    exchange: 'NASDAQ',
    mic_code: 'XNAS',
    instrument_type: 'Common Stock',
    country: 'United States',
    currency: 'USD',
  }

  for (const lookback of [504, 756, 1260]) {
    const payload = buildPredictionRequestPayload(
      { ...defaultPredictionConfig, lookback },
      asset,
    )
    assert.equal(payload.lookback, lookback)
    assert.equal(payload.classification_forecast_horizon, 1)
    assert.equal(payload.regression_forecast_horizon, 10)
  }
})

test('starting a new prediction request removes the previous forecast immediately', () => {
  const previousForecast = { predictionAvailable: true, predictedDirection: 'Up' }

  const nextForecast = clearPredictionResultForRequest(previousForecast)

  assert.equal(nextForecast, null)
})

test('switching assets immediately clears the prior result, error, and loading state', () => {
  assert.equal(
    predictionAssetChanged(
      { id: 1, symbol: 'AAPL', mic_code: 'XNAS' },
      { id: 2, symbol: 'NVDA', mic_code: 'XNAS' },
    ),
    true,
  )
  assert.equal(
    predictionAssetChanged(
      { id: 1, symbol: 'AAPL', mic_code: 'XNAS' },
      { id: 1, symbol: 'AAPL', mic_code: 'XNAS' },
    ),
    false,
  )
  assert.deepEqual(clearedPredictionViewState(), {
    currentForecast: null,
    requestError: '',
    isLoading: false,
  })
})

test('a failed request cannot leave the previous successful result visible', () => {
  const previousState = {
    currentForecast: { asset: { symbol: 'AAPL' }, predictionAvailable: true },
    requestError: '',
  }
  const nextState = { ...previousState, ...failedPredictionViewState(new Error('Request failed.')) }

  assert.equal(nextState.currentForecast, null)
  assert.equal(nextState.requestError, 'Request failed.')
})

test('only the newest prediction request can publish results or request state', () => {
  const guard = createLatestPredictionRequestGuard()
  let visibleResult = 'previous-result'
  const slowRequest = guard.start()
  const fastRequest = guard.start()

  if (guard.isCurrent(fastRequest)) visibleResult = 'newer-result'
  if (guard.isCurrent(slowRequest)) visibleResult = 'older-result'

  assert.equal(visibleResult, 'newer-result')
  assert.equal(guard.isCurrent(fastRequest), true)
  assert.equal(guard.isCurrent(slowRequest), false)
})

test('asset changes and unmounting invalidate in-flight prediction requests', () => {
  const guard = createLatestPredictionRequestGuard()
  const assetRequest = guard.start()
  guard.invalidate()
  assert.equal(guard.isCurrent(assetRequest), false)

  const mountedRequest = guard.start()
  guard.dispose()
  assert.equal(guard.isCurrent(mountedRequest), false)

  guard.activate()
  const remountedRequest = guard.start()
  assert.equal(guard.isCurrent(remountedRequest), true)
})

test('failed regression publication clears stale formal forecast fields', () => {
  const state = regressionPublicationState({
    regression_prediction_available: false,
    expected_return: 0.08,
    predicted_price: 108,
    regression_model: 'Old Model',
  })

  assert.deepEqual(state, {
    available: false,
    expectedReturn: null,
    predictedPrice: null,
    model: null,
  })
})

test('passed regression publication retains the current formal forecast fields', () => {
  const state = regressionPublicationState({
    regression_prediction_available: true,
    expected_return: -0.025,
    predicted_price: 97.5,
    regression_model: 'Ridge Regression',
  })

  assert.deepEqual(state, {
    available: true,
    expectedReturn: -0.025,
    predictedPrice: 97.5,
    model: 'Ridge Regression',
  })
})

test('available flag never converts missing regression values into zero forecasts', () => {
  const state = regressionPublicationState({
    regression_prediction_available: true,
    expected_return: null,
    predicted_price: null,
  })

  assert.equal(state.expectedReturn, null)
  assert.equal(state.predictedPrice, null)
})

test('quality gate failure displays the baseline message instead of a direction', () => {
  const independentTestReason = 'Independent Test: minimum class recall 0.030 is below the 0.200 minimum.'
  const message = predictionUnavailableMessage({
    prediction: { status: 'quality_gate_failed', message: independentTestReason },
    prediction_quality_gate: { classification: { passed: false } },
    predicted_direction: null,
  })

  assert.equal(message, independentTestReason)
})

test('quality gate failure has a safe fallback without backend details', () => {
  const message = predictionUnavailableMessage({
    prediction_quality_gate: { classification: { passed: false } },
  })

  assert.equal(message, QUALITY_GATE_UNAVAILABLE_MESSAGE)
})

test('regression failure reason uses only regression response fields', () => {
  assert.equal(
    regressionUnavailableMessage({
      prediction_unavailable_reason: 'Classification failed.',
      regression_prediction_unavailable_reason: 'Regression failed its independent Test gate.',
    }),
    'Regression failed its independent Test gate.',
  )
  assert.equal(regressionUnavailableMessage({}), REGRESSION_UNAVAILABLE_MESSAGE)
})
