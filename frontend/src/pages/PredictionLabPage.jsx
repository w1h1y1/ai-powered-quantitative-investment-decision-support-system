import { useEffect, useMemo, useRef, useState } from 'react'
import FeatureInfluence from '../components/prediction-lab/FeatureInfluence'
import ForecastChart from '../components/prediction-lab/ForecastChart'
import ForecastConfiguration from '../components/prediction-lab/ForecastConfiguration'
import ForecastHistory from '../components/prediction-lab/ForecastHistory'
import ForecastInterpretation from '../components/prediction-lab/ForecastInterpretation'
import ForecastOverview from '../components/prediction-lab/ForecastOverview'
import ForecastReliability from '../components/prediction-lab/ForecastReliability'
import ModelAgreement from '../components/prediction-lab/ModelAgreement'
import ModelComparison from '../components/prediction-lab/ModelComparison'
import ModelPerformance from '../components/prediction-lab/ModelPerformance'
import PriceForecastSummary from '../components/prediction-lab/PriceForecastSummary'
import ScenarioSimulation from '../components/prediction-lab/ScenarioSimulation'
import Icon from '../components/Icon'
import {
  defaultPredictionConfig,
  directionHorizonOptions,
  returnHorizonOptions,
} from '../data/predictionConfig'
import { predictionApi } from '../services/predictionApi'
import { securityApi } from '../services/securityApi'
import { normalizeSecuritySearchOption } from '../components/security/securitySearchModel'
import {
  buildPredictionRequestPayload,
  clearedPredictionViewState,
  clearPredictionResultForRequest,
  createLatestPredictionRequestGuard,
  failedPredictionViewState,
  predictionAssetChanged,
  predictionUnavailableMessage,
  regressionPublicationState,
  regressionUnavailableMessage,
  updatePredictionConfiguration,
} from '../components/prediction-lab/predictionRequestState'

function horizonLabel(options, value) {
  return options.find((option) => option.value === value)?.label
    ?? `${value} Trading ${value === 1 ? 'Day' : 'Days'}`
}

export function buildMarketDataView(response, configuration) {
  const technical = response.technical_indicators ?? {}
  const predictionAvailable = response.prediction_available === true
  const regressionPublication = regressionPublicationState(response)
  const regressionPredictionAvailable = regressionPublication.available
  const classificationForecastHorizon = Number(
    response.classification_forecast_horizon ?? configuration.classificationForecastHorizon,
  )
  const regressionForecastHorizon = Number(
    response.regression_forecast_horizon ?? configuration.regressionForecastHorizon,
  )
  const directionHorizonLabel = horizonLabel(
    directionHorizonOptions,
    classificationForecastHorizon,
  )
  const returnHorizonLabel = horizonLabel(
    returnHorizonOptions,
    regressionForecastHorizon,
  )
  const selectedModelKey = response.selected_model?.toLowerCase().replaceAll(' ', '-') ?? null
  const modelComparison = (response.model_comparison ?? []).map((model) => ({
    key: model.model.toLowerCase().replaceAll(' ', '-'),
    label: model.model,
    selected: model.selected === true,
    predictedDirection: model.predicted_direction === 'UP'
      ? 'Up'
      : model.predicted_direction === 'DOWN' ? 'Down' : 'Unavailable',
    probabilityIncrease: model.probability_increase == null
      ? null
      : Number(model.probability_increase) * 100,
    accuracy: Number(model.accuracy) * 100,
    precision: Number(model.precision) * 100,
    recall: Number(model.recall) * 100,
    f1: Number(model.f1) * 100,
    rocAuc: model.roc_auc == null ? null : Number(model.roc_auc),
    selectionScore: Number(model.selection_score) * 100,
    walkForwardQualityGate: model.walk_forward_quality_gate ?? model.quality_gate ?? null,
  }))
  const upModelCount = modelComparison.filter((model) => model.predictedDirection === 'Up').length
  const downModelCount = modelComparison.length - upModelCount
  const dominantModelCount = Math.max(upModelCount, downModelCount)
  const modelAgreement = predictionAvailable && modelComparison.length ? {
    agreement: dominantModelCount === modelComparison.length ? 'Strong' : 'Mixed',
    dominantDirection: upModelCount === downModelCount ? 'Mixed' : upModelCount > downModelCount ? 'Up' : 'Down',
    dominantCount: dominantModelCount,
    modelCount: modelComparison.length,
    significantDisagreement: upModelCount > 0 && downModelCount > 0,
    probabilityRange: `${Math.min(...modelComparison.map((model) => model.probabilityIncrease)).toFixed(1)}%–${Math.max(...modelComparison.map((model) => model.probabilityIncrease)).toFixed(1)}%`,
    summary: dominantModelCount === modelComparison.length
      ? 'Both classification models predict the same direction.'
      : 'The classification models predict different directions; review validation metrics and confidence carefully.',
  } : null
  const selectedMetrics = response.model_metrics ?? null
  const predictedDirection = predictionAvailable && response.predicted_direction === 'UP'
    ? 'Up'
    : predictionAvailable && response.predicted_direction === 'DOWN' ? 'Down' : null
  const probabilityIncrease = predictionAvailable
    && response.probability_increase != null
    && Number.isFinite(Number(response.probability_increase))
    ? Number(response.probability_increase) * 100
    : null
  const expectedReturn = regressionPublication.expectedReturn != null
    ? regressionPublication.expectedReturn * 100
    : null
  const classificationPredictionMessage = predictionAvailable
    ? null
    : predictionUnavailableMessage(response)
  const regressionPredictionMessage = regressionPredictionAvailable
    ? null
    : regressionUnavailableMessage(response)
  return {
    id: `market-data-${response.symbol}-${response.latest_market_date}-${response.lookback}-${classificationForecastHorizon}-${regressionForecastHorizon}`,
    asset: {
      symbol: response.symbol,
      name: response.security?.name ?? response.symbol,
      type: response.security?.asset_type === 'ETF' ? 'ETF' : 'Stock',
    },
    configuration: {
      ...configuration,
      model: selectedModelKey,
      classificationForecastHorizon,
      regressionForecastHorizon,
      directionHorizonLabel,
      returnHorizonLabel,
      // Temporary display-context aliases for older saved-context consumers.
      horizon: classificationForecastHorizon,
      horizonLabel: directionHorizonLabel,
      historicalWindowLabel: `${response.lookback} trading days`,
    },
    currentPrice: Number(response.current_price),
    latestMarketDate: response.latest_market_date,
    historicalDataCount: response.historical_data_count,
    technicalIndicators: technical,
    marketData: response.market_data,
    predictionAvailable,
    regressionPredictionAvailable,
    predictionStatus: response.prediction?.status ?? (predictionAvailable ? 'available' : 'insufficient_data'),
    predictionMessage: classificationPredictionMessage,
    classificationPredictionMessage,
    regressionPredictionMessage,
    predictionQualityGate: response.prediction_quality_gate ?? null,
    forecastSeries: {
      historical: (response.historical_data ?? []).map((bar) => ({ date: bar.date, price: Number(bar.close) })),
      forecast: [],
    },
    expectedPrice: regressionPublication.predictedPrice,
    priceSummary: regressionPredictionAvailable
      ? `Regression estimate from ${response.regression_model}; both Walk-Forward and independent Test regression quality gates passed.`
      : regressionPredictionMessage,
    forecastRange: { lower: null, upper: null },
    predictedDirection,
    probabilityIncrease,
    expectedReturn,
    confidence: predictionAvailable ? response.confidence ?? null : null,
    confidenceDetails: response.confidence_details ?? null,
    selectedModel: response.selected_model ?? null,
    selectedCandidateModel: response.selected_candidate_model
      ?? modelComparison.find((model) => model.selected)?.label
      ?? null,
    selectedCandidateThreshold: response.selected_candidate_threshold ?? null,
    regressionModel: regressionPublication.model,
    selectedRegressionCandidateModel: response.selected_regression_candidate_model ?? null,
    selectedRegressionCandidateParams: response.selected_regression_candidate_params ?? null,
    regressionWalkForwardQualityGate: response.regression_walk_forward_quality_gate ?? null,
    regressionIndependentTestQualityGate: response.regression_independent_test_quality_gate ?? null,
    finalRegressionQualityGate: response.final_regression_quality_gate ?? null,
    modelMetrics: selectedMetrics,
    modelComparison,
    modelSelectionMode: 'automatic',
    selectionReason: 'Selected using purged Walk-Forward Macro F1, Balanced Accuracy, ROC-AUC, minimum class recall, and cross-fold stability. The independent Test does not affect this selection.',
    scenarios: [],
    featureInfluence: [],
    reliability: null,
    modelAgreement,
    modelPerformance: selectedMetrics ? {
      accuracy: Number(selectedMetrics.accuracy) * 100,
      balancedAccuracy: Number(selectedMetrics.balanced_accuracy) * 100,
      precision: Number(selectedMetrics.precision) * 100,
      recall: Number(selectedMetrics.recall) * 100,
      f1: Number(selectedMetrics.f1) * 100,
      macroF1: Number(selectedMetrics.macro_f1) * 100,
      minimumClassRecall: Number(selectedMetrics.minimum_class_recall) * 100,
      rocAuc: selectedMetrics.roc_auc == null ? null : Number(selectedMetrics.roc_auc),
      baselineAccuracy: Number(selectedMetrics.majority_class_baseline_accuracy) * 100,
      trainingSamples: selectedMetrics.training_samples,
      validationSamples: selectedMetrics.validation_samples,
      testSamples: selectedMetrics.test_samples,
      classificationForecastHorizon,
      regressionForecastHorizon,
      classificationPurgeGap: response.classification_purge_gap ?? classificationForecastHorizon,
      regressionPurgeGap: response.regression_purge_gap ?? regressionForecastHorizon,
      walkForwardFolds: selectedMetrics.walk_forward_folds ?? [],
      independentTestQualityGate: response.independent_test_quality_gate
        ?? selectedMetrics.independent_test_quality_gate
        ?? null,
      finalClassificationQualityGate: response.final_classification_quality_gate
        ?? selectedMetrics.final_classification_quality_gate
        ?? null,
      regression: selectedMetrics.regression ?? null,
    } : null,
    interpretation: predictionAvailable
      ? regressionPredictionAvailable
        ? `${response.selected_model} estimates a ${predictedDirection} direction over ${directionHorizonLabel.toLowerCase()} with ${probabilityIncrease.toFixed(1)}% probability of an increase. ${response.regression_model} estimates a ${expectedReturn >= 0 ? '+' : ''}${expectedReturn.toFixed(2)}% return over ${returnHorizonLabel.toLowerCase()}, implying a price of ${new Intl.NumberFormat('en-US', { style: 'currency', currency: response.security?.currency || 'USD' }).format(Number(response.predicted_price))}. This is a model estimate based on chronological validation, not a guarantee.`
        : `${response.selected_model} estimates a ${predictedDirection} direction with ${probabilityIncrease.toFixed(1)}% probability of an increase. The regression candidate did not pass both return-prediction quality gates, so no expected return or predicted price is presented as reliable.`
      : null,
  }
}

function EmptyForecastState() {
  return (
    <section className="prediction-card prediction-empty-card" aria-labelledby="prediction-empty-title">
      <span className="prediction-empty-icon" aria-hidden="true"><Icon name="prediction" /></span>
      <h2 id="prediction-empty-title">No market data loaded yet.</h2>
      <p>Search for a stock or ETF, then load real historical OHLCV and technical indicators.</p>
    </section>
  )
}

export default function PredictionLabPage({ onNavigate, onOpenMarketAnalysis }) {
  const [config, setConfig] = useState(defaultPredictionConfig)
  const [assets, setAssets] = useState([])
  const [selectedAsset, setSelectedAsset] = useState(null)
  const [isAssetsLoading, setIsAssetsLoading] = useState(true)
  const [assetError, setAssetError] = useState('')
  const [currentForecast, setCurrentForecast] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [requestError, setRequestError] = useState('')
  const requestGuardRef = useRef(null)
  if (requestGuardRef.current === null) {
    requestGuardRef.current = createLatestPredictionRequestGuard()
  }

  useEffect(() => {
    requestGuardRef.current.activate()
    return () => requestGuardRef.current.dispose()
  }, [])

  useEffect(() => {
    let ignore = false
    securityApi.list()
      .then((response) => {
        if (ignore) return
        const nextAssets = (Array.isArray(response) ? response : [])
          .filter((security) => security?.is_active !== false)
          .map((security) => normalizeSecuritySearchOption(security))
          .filter(Boolean)
        setAssets(nextAssets)
        if (nextAssets.length) {
          setSelectedAsset((current) => current ?? nextAssets.find((asset) => asset.symbol === 'AAPL') ?? nextAssets[0])
          setConfig((current) => ({ ...current, symbol: current.symbol || (nextAssets.find((asset) => asset.symbol === 'AAPL') ?? nextAssets[0]).symbol }))
        }
      })
      .catch((error) => {
        if (!ignore) setAssetError(error.message || 'Unable to load available securities.')
      })
      .finally(() => {
        if (!ignore) setIsAssetsLoading(false)
      })
    return () => { ignore = true }
  }, [])

  const isConfigValid = useMemo(() => Boolean(selectedAsset?.symbol)
    && directionHorizonOptions.some((option) => option.value === config.classificationForecastHorizon)
    && returnHorizonOptions.some((option) => option.value === config.regressionForecastHorizon)
    && Number.isInteger(config.lookback), [config, selectedAsset])

  const updateConfig = (field, value) => setConfig((current) => (
    updatePredictionConfiguration(current, field, value)
  ))

  const selectAsset = (asset) => {
    if (predictionAssetChanged(selectedAsset, asset)) {
      requestGuardRef.current.invalidate()
      const clearedState = clearedPredictionViewState()
      setCurrentForecast(clearedState.currentForecast)
      setRequestError(clearedState.requestError)
      setIsLoading(clearedState.isLoading)
    }
    setSelectedAsset(asset)
    setAssetError('')
    setConfig((current) => ({ ...current, symbol: asset?.symbol ?? '' }))
  }

  const loadMarketData = async (event) => {
    event.preventDefault()
    if (!isConfigValid) return
    const requestId = requestGuardRef.current.start()
    setIsLoading(true)
    setRequestError('')
    setCurrentForecast(clearPredictionResultForRequest())
    try {
      const response = await predictionApi.generate(
        buildPredictionRequestPayload(config, selectedAsset),
      )
      if (!requestGuardRef.current.isCurrent(requestId)) return
      setCurrentForecast(buildMarketDataView(response, config))
    } catch (error) {
      if (!requestGuardRef.current.isCurrent(requestId)) return
      if (error?.name === 'AbortError') return
      const failedState = failedPredictionViewState(error)
      setRequestError(failedState.requestError)
      setCurrentForecast(failedState.currentForecast)
    } finally {
      if (requestGuardRef.current.isCurrent(requestId)) setIsLoading(false)
    }
  }

  return (
    <main className="main-content prediction-page-main">
      <section className="prediction-page-heading" aria-label="Prediction Lab introduction">
        <div>
          <p>Prediction research</p>
          <span>Real daily market data and technical indicators; model prediction will be added in the next phase.</span>
        </div>
        <div className="demo-data-status" aria-label="Prediction data status">
          <strong>Real Market Data</strong>
          <span>ML prediction enabled</span>
        </div>
      </section>

      <ForecastConfiguration
        config={config}
        assets={assets}
        selectedAsset={selectedAsset}
        isAssetsLoading={isAssetsLoading}
        isLoading={isLoading}
        isValid={isConfigValid}
        error={assetError}
        onChange={updateConfig}
        onSelectAsset={selectAsset}
        onSubmit={loadMarketData}
      />

      <div className="prediction-result-region" aria-busy={isLoading}>
        {requestError && <section className="prediction-card prediction-empty-card"><h2>Market data unavailable</h2><p>{requestError}</p></section>}
        {currentForecast ? (
          !currentForecast.predictionAvailable ? (
            <>
              <ForecastOverview forecast={currentForecast} />
              <PriceForecastSummary forecast={currentForecast} />
              <FeatureInfluence features={currentForecast.featureInfluence} technicalIndicators={currentForecast.technicalIndicators} />
              <ForecastChart forecast={currentForecast} />
              {currentForecast.modelComparison.length > 0 && currentForecast.modelPerformance && (
                <details className="prediction-research-details">
                  <summary><span><strong>Show Model and Fold Diagnostics</strong><small>Candidate models, independent Test metrics, and Walk-Forward folds</small></span><Icon name="chevron" /></summary>
                  <div className="prediction-research-content">
                    <ModelComparison forecast={currentForecast} />
                    <ModelPerformance forecast={currentForecast} />
                  </div>
                </details>
              )}
            </>
          ) : (
            <>
              <ForecastOverview forecast={currentForecast} />
              <PriceForecastSummary forecast={currentForecast} />
              <ForecastChart forecast={currentForecast} />
              <details className="prediction-research-details">
                <summary><span><strong>Show Research Details</strong><small>Model comparison, agreement, and historical performance</small></span><Icon name="chevron" /></summary>
                <div className="prediction-research-content">
                  <ModelComparison forecast={currentForecast} />
                  <div className="prediction-paired-grid">
                    <ModelAgreement agreement={currentForecast.modelAgreement} />
                    <ModelPerformance forecast={currentForecast} />
                  </div>
                </div>
              </details>
              <ScenarioSimulation scenarios={currentForecast.scenarios} />
              <div className="prediction-detail-stack">
                <FeatureInfluence features={currentForecast.featureInfluence} technicalIndicators={currentForecast.technicalIndicators} />
                <ForecastReliability reliability={currentForecast.reliability} />
              </div>
              <ForecastInterpretation
                forecast={currentForecast}
                onOpenInAIInsights={() => onNavigate('ai-insights')}
                onNavigate={onNavigate}
                onOpenMarketAnalysis={() => onOpenMarketAnalysis(currentForecast.asset.symbol)}
              />
            </>
          )
        ) : !requestError && <EmptyForecastState />}
      </div>

      {currentForecast?.predictionAvailable && currentForecast && (
        <ForecastHistory history={[]} currentForecastId={null} onOpen={() => {}} onDelete={() => {}} />
      )}
    </main>
  )
}
