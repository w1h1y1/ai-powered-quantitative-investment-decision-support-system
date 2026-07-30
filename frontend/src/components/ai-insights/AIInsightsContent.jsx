import { useCallback, useEffect, useRef, useState } from 'react'
import {
  aiInsightDisclaimer,
  aiInsightHistoryLimit,
  aiInsightHistoryStorageKey,
  defaultAIInsightConfig,
  selectedAIInsightStorageKey,
} from '../../data/aiInsightsMockData'
import {
  latestPredictionContextStorageKey,
  latestPredictionContextUpdatedEvent,
} from '../../data/predictionMockData'
import {
  createPredictionEvidenceFromContext,
  generateMockAIInsight,
  sanitizeAIInsightHistory,
  sanitizePredictionContext,
} from '../../services/aiInsightService'
import Icon from '../Icon'
import ConfidenceExplanation from './ConfidenceExplanation'
import DecisionOverview from './DecisionOverview'
import DecisionSummary from './DecisionSummary'
import EvidenceBreakdown from './EvidenceBreakdown'
import FactorLists from './FactorLists'
import InsightConfiguration from './InsightConfiguration'
import InsightHistory from './InsightHistory'
import RecommendedNextSteps from './RecommendedNextSteps'

function readLatestPredictionContext() {
  let storedPrediction

  try {
    storedPrediction = window.localStorage.getItem(latestPredictionContextStorageKey)
  } catch (error) {
    console.error('[AI Insights] Failed to read latestPredictionContext.', error)
    return null
  }

  if (storedPrediction === null) return null

  let parsedPrediction
  try {
    parsedPrediction = JSON.parse(storedPrediction)
  } catch (error) {
    console.warn('[AI Insights] latestPredictionContext contains invalid JSON.', error)
    return null
  }

  const predictionContext = sanitizePredictionContext(parsedPrediction)
  if (!predictionContext) {
    console.warn('[AI Insights] latestPredictionContext is invalid: asset and predictedDirection are required.')
  }
  return predictionContext
}

function readStoredAIInsightState() {
  let history = []

  try {
    const storedValue = window.localStorage.getItem(aiInsightHistoryStorageKey)
    if (storedValue !== null) history = sanitizeAIInsightHistory(JSON.parse(storedValue))
  } catch {
    history = []
  }

  const latestPredictionContext = readLatestPredictionContext()

  try {
    const selectedInsightId = window.localStorage.getItem(selectedAIInsightStorageKey)
    return {
      history,
      currentInsight: history.find((insight) => insight.id === selectedInsightId) ?? history[0] ?? null,
      latestPredictionContext,
    }
  } catch {
    return { history, currentInsight: history[0] ?? null, latestPredictionContext }
  }
}

function EmptyInsightState() {
  return (
    <section className="ai-insights-card ai-insights-empty-card" aria-labelledby="ai-insights-empty-title">
      <span className="ai-insights-empty-icon" aria-hidden="true">
        <Icon name="insights" />
      </span>
      <h2 id="ai-insights-empty-title">No rule-based insight generated yet.</h2>
      <p>Configure the analysis and generate an explainable decision-support summary.</p>
    </section>
  )
}

function LoadingInsightState() {
  return (
    <section className="ai-insights-card ai-insights-empty-card" aria-live="polite" aria-busy="true">
      <i className="ai-insights-spinner is-large" aria-hidden="true" />
      <h2>Generating Insight...</h2>
      <p>Combining technical signals, portfolio exposure, backtest evidence and market context.</p>
    </section>
  )
}

export default function AIInsightsContent({ onNavigate }) {
  const [initialState] = useState(readStoredAIInsightState)
  const [config, setConfig] = useState(() => ({
    ...defaultAIInsightConfig,
    ...(initialState.currentInsight?.configuration ?? {}),
    includePrediction: Boolean(initialState.latestPredictionContext),
  }))
  const [history, setHistory] = useState(initialState.history)
  const [currentInsight, setCurrentInsight] = useState(initialState.currentInsight)
  const [latestPredictionContext, setLatestPredictionContext] = useState(initialState.latestPredictionContext)
  const [isLoading, setIsLoading] = useState(false)
  const generateTimerRef = useRef(null)
  const resultsRef = useRef(null)
  const predictionContextSignatureRef = useRef(JSON.stringify(initialState.latestPredictionContext))

  const refreshLatestPredictionContext = useCallback(() => {
    const nextContext = readLatestPredictionContext()
    const nextSignature = JSON.stringify(nextContext)

    if (nextSignature !== predictionContextSignatureRef.current) {
      predictionContextSignatureRef.current = nextSignature
      setLatestPredictionContext(nextContext)
      setConfig((current) => ({
        ...current,
        includePrediction: Boolean(nextContext),
      }))
    }

    return nextContext
  }, [])

  useEffect(() => {
    const handleStorage = (event) => {
      if (event.key === latestPredictionContextStorageKey) refreshLatestPredictionContext()
    }

    refreshLatestPredictionContext()
    window.addEventListener('focus', refreshLatestPredictionContext)
    window.addEventListener('storage', handleStorage)
    window.addEventListener(latestPredictionContextUpdatedEvent, refreshLatestPredictionContext)

    return () => {
      window.removeEventListener('focus', refreshLatestPredictionContext)
      window.removeEventListener('storage', handleStorage)
      window.removeEventListener(latestPredictionContextUpdatedEvent, refreshLatestPredictionContext)
    }
  }, [refreshLatestPredictionContext])

  useEffect(() => {
    try {
      window.localStorage.setItem(aiInsightHistoryStorageKey, JSON.stringify(history))
    } catch {
      // React state remains the source of truth if browser storage is unavailable.
    }
  }, [history])

  useEffect(() => {
    try {
      if (currentInsight) {
        window.localStorage.setItem(selectedAIInsightStorageKey, currentInsight.id)
      } else if (!isLoading) {
        window.localStorage.removeItem(selectedAIInsightStorageKey)
      }
    } catch {
      // The visible insight remains available even if browser storage is unavailable.
    }
  }, [currentInsight, isLoading])

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
    if (field === 'includePrediction' && !latestPredictionContext) return
    setConfig((current) => ({ ...current, [field]: value }))
  }

  const generateInsight = (event) => {
    event.preventDefault()
    if (generateTimerRef.current) window.clearTimeout(generateTimerRef.current)

    setIsLoading(true)
    setCurrentInsight(null)

    generateTimerRef.current = window.setTimeout(() => {
      const nextInsight = generateMockAIInsight(config, new Date(), latestPredictionContext)
      setCurrentInsight(nextInsight)
      setHistory((current) => [
        nextInsight,
        ...current.filter((insight) => insight.id !== nextInsight.id),
      ].slice(0, aiInsightHistoryLimit))
      setIsLoading(false)
      generateTimerRef.current = null
      scrollToResults()
    }, 650)
  }

  const reopenInsight = (insight) => {
    if (generateTimerRef.current) window.clearTimeout(generateTimerRef.current)
    generateTimerRef.current = null
    setIsLoading(false)
    setConfig({
      ...defaultAIInsightConfig,
      ...insight.configuration,
      includePrediction: Boolean(latestPredictionContext && insight.configuration.includePrediction),
    })
    setCurrentInsight(insight)
    scrollToResults()
  }

  const deleteInsight = (insightId) => {
    const deletedIndex = history.findIndex((insight) => insight.id === insightId)
    const nextHistory = history.filter((insight) => insight.id !== insightId)
    setHistory(nextHistory)

    if (currentInsight?.id !== insightId) return

    const nextInsight = nextHistory[deletedIndex]
      ?? nextHistory[deletedIndex - 1]
      ?? nextHistory[0]
      ?? null

    setCurrentInsight(nextInsight)
    if (nextInsight) {
      setConfig({
        ...defaultAIInsightConfig,
        ...nextInsight.configuration,
        includePrediction: Boolean(latestPredictionContext && nextInsight.configuration.includePrediction),
      })
    }
    scrollToResults()
  }

  const livePredictionEvidence = latestPredictionContext
    ? createPredictionEvidenceFromContext(config, latestPredictionContext)
    : {
        included: false,
        status: 'unavailable',
        metrics: [],
        explanation: 'No forecast context is currently available.',
      }

  return (
    <main className="main-content ai-insights-page-main">
      <section className="ai-insights-page-heading" aria-labelledby="ai-insights-page-title">
        <div>
          <p>Decision support</p>
          <h2 id="ai-insights-page-title">AI Insights</h2>
          <span>Explainable decision support based on technical signals, portfolio exposure, and strategy evidence.</span>
        </div>
        <div className="demo-data-status" aria-label="Demo analysis status">
          <strong>Demo Analysis</strong>
          <span>Rule-based mock insight</span>
        </div>
      </section>

      <InsightConfiguration
        config={config}
        hasPredictionContext={Boolean(latestPredictionContext)}
        isLoading={isLoading}
        onChange={updateConfig}
        onSubmit={generateInsight}
      />

      <div className="ai-insights-result-region" ref={resultsRef}>
        {isLoading ? (
          <LoadingInsightState />
        ) : currentInsight ? (
          <>
            <DecisionOverview insight={currentInsight} />
            <DecisionSummary insight={currentInsight} />
            <EvidenceBreakdown
              insight={currentInsight}
              predictionEvidenceOverride={livePredictionEvidence}
              onAnalysePredictionAsset={(symbol) => updateConfig('symbol', symbol)}
            />
            <FactorLists
              supportingFactors={currentInsight.supportingFactors}
              riskFactors={currentInsight.riskFactors}
            />
            <RecommendedNextSteps
              insight={currentInsight}
              steps={currentInsight.recommendedNextSteps}
              onNavigate={onNavigate}
            />
            <ConfidenceExplanation explanation={currentInsight.confidenceExplanation} />
          </>
        ) : (
          <EmptyInsightState />
        )}

        <aside className="ai-insights-disclaimer" aria-label="Rule-based insight risk disclosure">
          <Icon name="shield" />
          <span>{currentInsight?.disclaimer ?? aiInsightDisclaimer}</span>
        </aside>
      </div>

      <InsightHistory
        history={history}
        currentInsightId={currentInsight?.id}
        onReopen={reopenInsight}
        onDelete={deleteInsight}
      />
    </main>
  )
}
