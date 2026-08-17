import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

let vite
let buildMarketDataView
let ForecastOverview
let PriceForecastSummary

before(async () => {
  vite = await createServer({
    appType: 'custom',
    server: { middlewareMode: true },
  })
  ;({ buildMarketDataView } = await vite.ssrLoadModule('/src/pages/PredictionLabPage.jsx'))
  ;({ default: ForecastOverview } = await vite.ssrLoadModule(
    '/src/components/prediction-lab/ForecastOverview.jsx',
  ))
  ;({ default: PriceForecastSummary } = await vite.ssrLoadModule(
    '/src/components/prediction-lab/PriceForecastSummary.jsx',
  ))
})

after(async () => {
  await vite?.close()
})

function responseFor({
  classificationAvailable,
  regressionAvailable,
  classificationHorizon = 5,
  regressionHorizon = 20,
}) {
  return {
    symbol: 'AAPL',
    security: {
      name: 'Apple Inc.',
      asset_type: 'Common Stock',
      currency: 'USD',
    },
    classification_forecast_horizon: classificationHorizon,
    regression_forecast_horizon: regressionHorizon,
    lookback: 504,
    current_price: 200,
    latest_market_date: '2026-08-10',
    historical_data_count: 504,
    historical_data: [],
    market_data: { source: 'Twelve Data' },
    technical_indicators: { volatility: 24.5 },
    model_comparison: [],
    model_metrics: null,
    prediction_available: classificationAvailable,
    prediction_unavailable_reason: classificationAvailable
      ? null
      : 'Direction model failed its independent Test quality gate.',
    prediction: classificationAvailable
      ? { status: 'available' }
      : {
        status: 'quality_gate_failed',
        message: 'Direction model failed its independent Test quality gate.',
      },
    prediction_quality_gate: {
      classification: { passed: classificationAvailable },
      regression: { passed: regressionAvailable },
    },
    predicted_direction: 'UP',
    probability_increase: 0.64,
    confidence: 'Medium',
    selected_model: classificationAvailable ? 'Logistic Regression' : null,
    regression_prediction_available: regressionAvailable,
    regression_prediction_unavailable_reason: regressionAvailable
      ? null
      : 'Return model did not beat the zero-return baseline.',
    expected_return: regressionAvailable ? 0.025 : 0.15,
    predicted_price: regressionAvailable ? 205 : 230,
    regression_model: regressionAvailable ? 'Random Forest Regressor' : null,
    selected_regression_candidate_model: regressionAvailable ? null : 'Random Forest Regressor',
  }
}

function renderPrediction(response) {
  const forecast = buildMarketDataView(response, {
    symbol: 'AAPL',
    classificationForecastHorizon: 1,
    regressionForecastHorizon: 10,
    lookback: 504,
  })
  const html = renderToStaticMarkup(React.createElement(
    React.Fragment,
    null,
    React.createElement(ForecastOverview, { forecast }),
    React.createElement(PriceForecastSummary, { forecast }),
  ))
  return {
    forecast,
    text: html
      .replace(/<[^>]+>/g, ' ')
      .replace(/&amp;/g, '&')
      .replace(/\s+/g, ' ')
      .trim(),
  }
}

test('classification and regression failures show response-horizon N/A values and separate reasons', () => {
  const { forecast, text } = renderPrediction(responseFor({
    classificationAvailable: false,
    regressionAvailable: false,
    classificationHorizon: 5,
    regressionHorizon: 20,
  }))

  assert.match(text, /5 Trading Days Direction N\/A/)
  assert.match(text, /5 Trading Days Probability of Increase N\/A/)
  assert.match(text, /20 Trading Days Expected Return N\/A/)
  assert.match(text, /20 Trading Days Predicted Price N\/A/)
  assert.match(text, /Direction Prediction Unavailable Direction model failed its independent Test quality gate\./)
  assert.match(text, /Return Prediction Unavailable Return model did not beat the zero-return baseline\./)
  assert.equal(forecast.predictedDirection, null)
  assert.equal(forecast.probabilityIncrease, null)
  assert.equal(forecast.expectedReturn, null)
  assert.equal(forecast.expectedPrice, null)
})

test('classification failure does not suppress a successful regression forecast', () => {
  const { text } = renderPrediction(responseFor({
    classificationAvailable: false,
    regressionAvailable: true,
    classificationHorizon: 1,
    regressionHorizon: 10,
  }))

  assert.match(text, /1 Trading Day Direction N\/A/)
  assert.match(text, /1 Trading Day Probability of Increase N\/A/)
  assert.match(text, /Direction Prediction Unavailable Direction model failed its independent Test quality gate\./)
  assert.match(text, /10 Trading Days Expected Return \+2\.5%/)
  assert.match(text, /10 Trading Days Predicted Price \$205\.00/)
  assert.doesNotMatch(text, /Return Prediction Unavailable/)
})

test('regression failure does not suppress a successful classification forecast', () => {
  const { text } = renderPrediction(responseFor({
    classificationAvailable: true,
    regressionAvailable: false,
    classificationHorizon: 5,
    regressionHorizon: 20,
  }))

  assert.match(text, /5 Trading Days Direction Up/)
  assert.match(text, /5 Trading Days Probability of Increase 64\.0%/)
  assert.match(text, /20 Trading Days Expected Return N\/A/)
  assert.match(text, /20 Trading Days Predicted Price N\/A/)
  assert.match(text, /Return Prediction Unavailable Return model did not beat the zero-return baseline\./)
  assert.doesNotMatch(text, /Direction Prediction Unavailable/)
})

test('successful classification and regression both publish their own horizon results', () => {
  const { text } = renderPrediction(responseFor({
    classificationAvailable: true,
    regressionAvailable: true,
    classificationHorizon: 1,
    regressionHorizon: 10,
  }))

  assert.match(text, /1 Trading Day Direction Up/)
  assert.match(text, /1 Trading Day Probability of Increase 64\.0%/)
  assert.match(text, /10 Trading Days Expected Return \+2\.5%/)
  assert.match(text, /10 Trading Days Predicted Price \$205\.00/)
  assert.doesNotMatch(text, /Prediction Unavailable/)
})
