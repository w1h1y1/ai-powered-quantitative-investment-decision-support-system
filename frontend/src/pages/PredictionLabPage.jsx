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
  forecastHorizonOptions,
  historicalWindowOptions,
  latestPredictionContextStorageKey,
  latestPredictionContextUpdatedEvent,
  predictionAssets,
  predictionDisclaimer,
  predictionHistoryLimit,
  predictionHistoryStorageKey,
  selectedForecastStorageKey,
} from '../data/predictionMockData'
import {
  createPredictionContext,
  generateMockForecast,
  sanitizeForecastHistory,
} from '../services/predictionService'

function readStoredForecastState() {
  let history = []

  try {
    const storedValue = window.localStorage.getItem(predictionHistoryStorageKey)
    if (storedValue !== null) history = sanitizeForecastHistory(JSON.parse(storedValue))
  } catch {
    history = []
  }

  try {
    const selectedForecastId = window.localStorage.getItem(selectedForecastStorageKey)
    return {
      history,
      currentForecast: history.find((forecast) => forecast.id === selectedForecastId) ?? history[0] ?? null,
    }
  } catch {
    return { history, currentForecast: history[0] ?? null }
  }
}

function EmptyForecastState() {
  return (
    <section className="prediction-card prediction-empty-card" aria-labelledby="prediction-empty-title">
      <span className="prediction-empty-icon" aria-hidden="true"><Icon name="prediction" /></span>
      <h2 id="prediction-empty-title">No forecast generated yet.</h2>
      <p>Configure the prediction and generate a probabilistic market forecast.</p>
    </section>
  )
}

function LoadingForecastState() {
  return (
    <section className="prediction-card prediction-empty-card" aria-live="polite" aria-busy="true">
      <i className="prediction-spinner is-large" aria-hidden="true" />
      <h2>Generating Forecast...</h2>
      <p>Applying deterministic model, horizon, feature, and uncertainty rules.</p>
    </section>
  )
}

function saveLatestPredictionContext(forecast) {
  try {
    const predictionContext = createPredictionContext(forecast)
    window.localStorage.setItem(
      latestPredictionContextStorageKey,
      JSON.stringify(predictionContext),
    )
    window.dispatchEvent(new Event(latestPredictionContextUpdatedEvent))
  } catch (error) {
    console.error('[Prediction Lab] Failed to save latestPredictionContext.', error)
  }
}

export default function PredictionLabPage({ onNavigate, onOpenMarketAnalysis }) {
  const [initialState] = useState(readStoredForecastState)
  const [config, setConfig] = useState(() => ({
    ...defaultPredictionConfig,
    ...(initialState.currentForecast?.configuration ?? {}),
  }))
  const [history, setHistory] = useState(initialState.history)
  const [currentForecast, setCurrentForecast] = useState(initialState.currentForecast)
  const [isLoading, setIsLoading] = useState(false)
  const generateTimerRef = useRef(null)
  const resultsRef = useRef(null)

  const isConfigValid = useMemo(() => (
    predictionAssets.some((asset) => asset.symbol === config.assetSymbol)
    && forecastHorizonOptions.some((option) => option.value === config.horizon)
    && historicalWindowOptions.some((option) => option.value === config.historicalWindow)
  ), [config])

  useEffect(() => {
    try {
      window.localStorage.setItem(predictionHistoryStorageKey, JSON.stringify(history))
    } catch {
      // React state remains available when browser storage is unavailable.
    }
  }, [history])

  useEffect(() => {
    try {
      if (currentForecast) {
        window.localStorage.setItem(selectedForecastStorageKey, currentForecast.id)
      } else if (!isLoading) {
        window.localStorage.removeItem(selectedForecastStorageKey)
      }
    } catch {
      // The visible forecast remains the source of truth when storage is unavailable.
    }
  }, [currentForecast, isLoading])

  useEffect(() => () => {
    if (generateTimerRef.current) window.clearTimeout(generateTimerRef.current)
  }, [])

  const scrollToResults = () => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      })
    })
  }

  const updateConfig = (field, value) => {
    setConfig((current) => ({ ...current, [field]: value }))
  }

  const generateForecast = (event) => {
    event.preventDefault()
    if (!isConfigValid) return
    if (generateTimerRef.current) window.clearTimeout(generateTimerRef.current)

    setIsLoading(true)

    generateTimerRef.current = window.setTimeout(() => {
      const nextForecast = generateMockForecast(config)
      saveLatestPredictionContext(nextForecast)
      setCurrentForecast(nextForecast)
      setHistory((current) => [
        nextForecast,
        ...current.filter((forecast) => forecast.id !== nextForecast.id),
      ].slice(0, predictionHistoryLimit))
      setIsLoading(false)
      generateTimerRef.current = null
      scrollToResults()
    }, 650)
  }

  const openForecast = (forecast) => {
    if (generateTimerRef.current) window.clearTimeout(generateTimerRef.current)
    generateTimerRef.current = null
    setIsLoading(false)
    setConfig({ ...defaultPredictionConfig, ...forecast.configuration })
    setCurrentForecast(forecast)
    scrollToResults()
  }

  const deleteForecast = (forecastId) => {
    const deletedIndex = history.findIndex((forecast) => forecast.id === forecastId)
    const nextHistory = history.filter((forecast) => forecast.id !== forecastId)
    setHistory(nextHistory)

    if (currentForecast?.id !== forecastId) return

    const nextForecast = nextHistory[deletedIndex]
      ?? nextHistory[deletedIndex - 1]
      ?? nextHistory[0]
      ?? null
    setCurrentForecast(nextForecast)
    if (nextForecast) setConfig({ ...defaultPredictionConfig, ...nextForecast.configuration })
    scrollToResults()
  }

  const openInAIInsights = () => onNavigate('ai-insights')

  return (
    <main className="main-content prediction-page-main">
      <section className="prediction-page-heading" aria-label="Prediction Lab introduction">
        <div>
          <p>Probabilistic research</p>
          <span>Explore probabilistic market forecasts, model comparisons, and simulated future scenarios.</span>
        </div>
        <div className="demo-data-status" aria-label="Demo forecast status">
          <strong>Demo Forecast</strong>
          <span>Deterministic mock prediction</span>
        </div>
      </section>

      <ForecastConfiguration
        config={config}
        isLoading={isLoading}
        isValid={isConfigValid}
        onChange={updateConfig}
        onSubmit={generateForecast}
      />

      <div className="prediction-result-region" ref={resultsRef} aria-busy={isLoading}>
        {isLoading && !currentForecast ? (
          <LoadingForecastState />
        ) : currentForecast ? (
          <>
            <ForecastOverview forecast={currentForecast} />
            <PriceForecastSummary forecast={currentForecast} />
            <ForecastChart forecast={currentForecast} />
            <details className="prediction-research-details">
              <summary>
                <span>
                  <strong>Show Research Details</strong>
                  <small>Model comparison, agreement, and simulated historical performance</small>
                </span>
                <Icon name="chevron" />
              </summary>
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
              <FeatureInfluence features={currentForecast.featureInfluence} />
              <ForecastReliability reliability={currentForecast.reliability} />
            </div>

            <ForecastInterpretation
              forecast={currentForecast}
              onOpenInAIInsights={openInAIInsights}
              onNavigate={onNavigate}
              onOpenMarketAnalysis={() => onOpenMarketAnalysis(currentForecast.asset.symbol)}
            />
          </>
        ) : (
          <EmptyForecastState />
        )}

        <aside className="prediction-disclaimer" aria-label="Rule-based forecast risk disclosure">
          <Icon name="shield" />
          <span>{currentForecast?.disclaimer ?? predictionDisclaimer}</span>
        </aside>
      </div>

      <ForecastHistory
        history={history}
        currentForecastId={currentForecast?.id}
        onOpen={openForecast}
        onDelete={deleteForecast}
      />
    </main>
  )
}
