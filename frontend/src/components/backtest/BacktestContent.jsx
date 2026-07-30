import { useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../Icon'
import { createPortfolioAssetUniverse } from '../../data/portfolioData'
import {
  backtestHistoryLimit,
  backtestHistoryStorageKey,
  backtestStrategies,
  createMockBacktestResult,
  defaultBacktestConfig,
  legacySelectedBacktestStorageKey,
  sanitizeBacktestHistory,
  selectedBacktestStorageKey,
  validateBacktestConfig,
} from '../../data/backtestData'
import BacktestConfiguration from './BacktestConfiguration'
import BacktestHistory from './BacktestHistory'
import BacktestResults from './BacktestResults'

function readStoredHistory(assets) {
  try {
    const storedValue = window.localStorage.getItem(backtestHistoryStorageKey)
    if (storedValue === null) return []
    return sanitizeBacktestHistory(JSON.parse(storedValue), assets.map((asset) => asset.symbol))
  } catch {
    return []
  }
}

function readStoredBacktestState(assets) {
  const history = readStoredHistory(assets)

  try {
    const selectedBacktestId = window.localStorage.getItem(selectedBacktestStorageKey)
      ?? window.localStorage.getItem(legacySelectedBacktestStorageKey)
    return {
      history,
      currentResult: history.find((result) => result.id === selectedBacktestId) ?? history[0] ?? null,
    }
  } catch {
    return { history, currentResult: history[0] ?? null }
  }
}

export default function BacktestContent({ stocks }) {
  const assets = useMemo(() => createPortfolioAssetUniverse(stocks), [stocks])
  const [initialBacktestState] = useState(() => readStoredBacktestState(assets))
  const [config, setConfig] = useState(() => ({
    ...defaultBacktestConfig,
    ...(initialBacktestState.currentResult?.config ?? {}),
    symbol: initialBacktestState.currentResult?.config.symbol
      ?? (assets.some((asset) => asset.symbol === defaultBacktestConfig.symbol)
        ? defaultBacktestConfig.symbol
        : assets[0]?.symbol ?? ''),
  }))
  const [history, setHistory] = useState(initialBacktestState.history)
  const [currentResult, setCurrentResult] = useState(initialBacktestState.currentResult)
  const [isLoading, setIsLoading] = useState(false)
  const runTimerRef = useRef(null)
  const resultsRef = useRef(null)

  const selectedAsset = useMemo(
    () => assets.find((asset) => asset.symbol === config.symbol) ?? assets[0],
    [assets, config.symbol],
  )
  const selectedStrategy = useMemo(
    () => backtestStrategies.find((strategy) => strategy.id === config.strategyId) ?? backtestStrategies[0],
    [config.strategyId],
  )
  const errors = useMemo(() => validateBacktestConfig(config), [config])

  useEffect(() => {
    try {
      window.localStorage.setItem(backtestHistoryStorageKey, JSON.stringify(history))
    } catch {
      // React state remains the source of truth if browser storage is unavailable.
    }
  }, [history])

  useEffect(() => {
    try {
      if (currentResult) {
        window.localStorage.setItem(selectedBacktestStorageKey, currentResult.id)
        window.localStorage.removeItem(legacySelectedBacktestStorageKey)
      } else if (!isLoading) {
        window.localStorage.removeItem(selectedBacktestStorageKey)
        window.localStorage.removeItem(legacySelectedBacktestStorageKey)
      }
    } catch {
      // The visible result remains available even if browser storage is unavailable.
    }
  }, [currentResult, isLoading])

  useEffect(() => () => {
    if (runTimerRef.current) window.clearTimeout(runTimerRef.current)
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

  const runBacktest = (event) => {
    event.preventDefault()
    if (Object.keys(validateBacktestConfig(config)).length || !selectedAsset) return

    if (runTimerRef.current) window.clearTimeout(runTimerRef.current)
    setIsLoading(true)
    setCurrentResult(null)

    runTimerRef.current = window.setTimeout(() => {
      // This isolated generator can be replaced by a future Django REST API call.
      const result = createMockBacktestResult(config, selectedAsset)
      setCurrentResult(result)
      setHistory((current) => [
        result,
        ...current.filter((item) => item.id !== result.id),
      ].slice(0, backtestHistoryLimit))
      setIsLoading(false)
      runTimerRef.current = null
      scrollToResults()
    }, 700)
  }

  const reopenResult = (result) => {
    if (runTimerRef.current) window.clearTimeout(runTimerRef.current)
    runTimerRef.current = null
    setIsLoading(false)
    setConfig({ ...defaultBacktestConfig, ...result.config })
    setCurrentResult(result)
    scrollToResults()
  }

  const deleteResult = (resultId) => {
    const deletedIndex = history.findIndex((result) => result.id === resultId)
    const nextHistory = history.filter((result) => result.id !== resultId)
    setHistory(nextHistory)

    if (currentResult?.id !== resultId) return

    const nextResult = nextHistory[deletedIndex]
      ?? nextHistory[deletedIndex - 1]
      ?? nextHistory[0]
      ?? null

    setCurrentResult(nextResult)
    if (nextResult) setConfig({ ...defaultBacktestConfig, ...nextResult.config })
    scrollToResults()
  }

  return (
    <main className="main-content backtest-page-main">
      <section className="backtest-page-intro" aria-label="Backtest overview">
        <strong>Historical Strategy Simulation</strong>
        <span>Configure and compare rule-based strategies using structured demo market data.</span>
      </section>

      <BacktestConfiguration
        assets={assets}
        strategies={backtestStrategies}
        selectedAsset={selectedAsset}
        selectedStrategy={selectedStrategy}
        config={config}
        errors={errors}
        isLoading={isLoading}
        onChange={updateConfig}
        onSubmit={runBacktest}
      />

      <div className="backtest-result-region" ref={resultsRef}>
        {isLoading ? (
          <section className="backtest-card backtest-state-card" aria-live="polite" aria-busy="true">
            <i className="backtest-loading-spinner is-large" aria-hidden="true" />
            <h2>Running Backtest...</h2>
            <p>Generating strategy signals, risk metrics and trade history.</p>
          </section>
        ) : currentResult ? (
          <BacktestResults result={currentResult} />
        ) : (
          <section className="backtest-card backtest-state-card" aria-labelledby="backtest-empty-title">
            <span className="backtest-state-icon" aria-hidden="true"><Icon name="strategy" /></span>
            <h2 id="backtest-empty-title">No backtest result selected.</h2>
            <p>Run a valid configuration above, or reopen a saved result from Backtest History.</p>
          </section>
        )}
      </div>

      <BacktestHistory history={history} onReopen={reopenResult} onDelete={deleteResult} />
    </main>
  )
}
