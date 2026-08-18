import { useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../Icon'
import {
  backtestHistoryLimit,
  backtestHistoryStorageKey,
  backtestStrategies,
  buildBacktestFailureState,
  createDefaultBacktestConfig,
  createBacktestRunRequest,
  legacySelectedBacktestStorageKey,
  normalizeBacktestResult,
  sanitizeBacktestBenchmarkSymbol,
  sanitizeBacktestHistory,
  selectedBacktestStorageKey,
  validateBacktestConfig,
} from '../../data/backtestData'
import { backtestApi } from '../../services/backtestApi'
import { securityApi } from '../../services/securityApi'
import { normalizeSecuritySearchOption } from '../security/securitySearchModel'
import BacktestConfiguration from './BacktestConfiguration'
import BacktestHistory from './BacktestHistory'
import BacktestResults from './BacktestResults'

function readStoredHistory() {
  try {
    const storedValue = window.localStorage.getItem(backtestHistoryStorageKey)
    if (storedValue === null) return []
    return sanitizeBacktestHistory(JSON.parse(storedValue))
  } catch {
    return []
  }
}

function readStoredBacktestState() {
  const history = readStoredHistory()

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

export default function BacktestContent() {
  const [assets, setAssets] = useState([])
  const [isAssetsLoading, setIsAssetsLoading] = useState(true)
  const [assetsError, setAssetsError] = useState('')
  const [initialBacktestState] = useState(() => readStoredBacktestState())
  const [config, setConfig] = useState(() => createDefaultBacktestConfig())
  const [history, setHistory] = useState(initialBacktestState.history)
  const [currentResult, setCurrentResult] = useState(initialBacktestState.currentResult)
  const [selectedAssetOverride, setSelectedAssetOverride] = useState(
    () => normalizeSecuritySearchOption(initialBacktestState.currentResult?.asset),
  )
  const [isLoading, setIsLoading] = useState(false)
  const [runError, setRunError] = useState(null)
  const [sectorContext, setSectorContext] = useState(null)
  const sectorContextRequestIdRef = useRef(0)

  const selectedAsset = useMemo(
    () => (
      assets.find((asset) => asset.symbol === config.symbol)
      ?? (selectedAssetOverride?.symbol === config.symbol ? selectedAssetOverride : null)
    ),
    [assets, config.symbol, selectedAssetOverride],
  )
  const selectedBenchmark = useMemo(
    () => assets.find((asset) => asset.symbol === config.benchmarkSymbol) ?? null,
    [assets, config.benchmarkSymbol],
  )
  const selectedStrategy = useMemo(
    () => backtestStrategies.find((strategy) => strategy.id === config.strategyId) ?? backtestStrategies[0],
    [config.strategyId],
  )
  const availableBenchmarkSymbols = useMemo(() => {
    const allowed = (
      Array.isArray(sectorContext?.allowed_benchmarks)
      && sectorContext.allowed_benchmarks.length
    )
      ? sectorContext.allowed_benchmarks
      : ['SPY']
    return allowed.filter((symbol) => assets.some((asset) => asset.symbol === symbol))
  }, [assets, sectorContext])
  const errors = useMemo(() => {
    const validationErrors = validateBacktestConfig(config)
    if (assetsError) validationErrors.symbol = assetsError
    if (!isAssetsLoading && !assets.length) {
      validationErrors.symbol = 'No active securities are available for backtesting.'
    }
    if (!isAssetsLoading && assets.length && !selectedBenchmark) {
      validationErrors.benchmarkSymbol = 'The selected benchmark is not available.'
    }
    if (
      selectedAsset
      && availableBenchmarkSymbols.length
      && !availableBenchmarkSymbols.includes(config.benchmarkSymbol)
    ) {
      validationErrors.benchmarkSymbol = 'The selected benchmark is not valid for the selected asset.'
    }
    return validationErrors
  }, [
    assets.length,
    assetsError,
    availableBenchmarkSymbols,
    config,
    isAssetsLoading,
    selectedAsset,
    selectedBenchmark,
  ])

  useEffect(() => {
    let ignore = false
    setIsAssetsLoading(true)
    setAssetsError('')

    securityApi.list()
      .then((response) => {
        if (ignore) return
        const nextAssets = (Array.isArray(response) ? response : [])
          .filter((security) => security?.is_active !== false)
          .map((security) => normalizeSecuritySearchOption(security))
          .filter(Boolean)
        setAssets(nextAssets)
      })
      .catch((error) => {
        if (ignore) return
        setAssets([])
        setAssetsError(error.message || 'Security API request failed.')
      })
      .finally(() => {
        if (!ignore) setIsAssetsLoading(false)
      })

    return () => {
      ignore = true
    }
  }, [])

  useEffect(() => {
    if (!assets.length) return
    setConfig((current) => {
      const nextSymbol = assets.some((asset) => asset.symbol === current.symbol)
        ? current.symbol
        : assets[0].symbol
      const nextBenchmark = sanitizeBacktestBenchmarkSymbol(
        current.benchmarkSymbol,
        assets.map((asset) => asset.symbol),
      )
      if (nextSymbol === current.symbol && nextBenchmark === current.benchmarkSymbol) return current
      return { ...current, symbol: nextSymbol, benchmarkSymbol: nextBenchmark }
    })
  }, [assets])

  useEffect(() => {
    setSectorContext(null)
    if (!selectedAsset?.id) return undefined

    const requestId = sectorContextRequestIdRef.current + 1
    sectorContextRequestIdRef.current = requestId
    let ignore = false

    securityApi.sectorContext({ securityId: selectedAsset.id })
      .then((payload) => {
        if (!ignore && sectorContextRequestIdRef.current === requestId) {
          setSectorContext(payload)
          const benchmarkAssets = (Array.isArray(payload?.benchmarks) ? payload.benchmarks : [])
            .map((security) => normalizeSecuritySearchOption(security))
            .filter(Boolean)
          if (benchmarkAssets.length) {
            setAssets((currentAssets) => {
              const mergedAssets = [...currentAssets]
              benchmarkAssets.forEach((benchmark) => {
                if (!mergedAssets.some((asset) => asset.symbol === benchmark.symbol)) {
                  mergedAssets.push(benchmark)
                }
              })
              return mergedAssets
            })
          }
        }
      })
      .catch(() => {
        if (!ignore && sectorContextRequestIdRef.current === requestId) {
          setSectorContext(null)
        }
      })

    return () => {
      ignore = true
    }
  }, [selectedAsset?.id])

  useEffect(() => {
    if (!selectedAsset?.id || !availableBenchmarkSymbols.length) return
    const nextBenchmark = sanitizeBacktestBenchmarkSymbol(
      config.benchmarkSymbol,
      availableBenchmarkSymbols,
    )
    if (nextBenchmark !== config.benchmarkSymbol) {
      setConfig((current) => ({ ...current, benchmarkSymbol: nextBenchmark }))
    }
  }, [availableBenchmarkSymbols, config.benchmarkSymbol, selectedAsset?.id])

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

  const updateConfig = (field, value) => {
    setConfig((current) => ({ ...current, [field]: value }))
  }

  const selectAsset = (asset) => {
    setSelectedAssetOverride(asset)
    setConfig((current) => ({ ...current, symbol: asset?.symbol ?? '' }))
  }

  const executeBacktest = async (request) => {
    setIsLoading(true)
    setRunError(null)
    setCurrentResult(null)

    try {
      const response = await backtestApi.run(request.payload)
      const result = normalizeBacktestResult(response, request.config)
      setSelectedAssetOverride(normalizeSecuritySearchOption(result.asset))
      setCurrentResult(result)
      setHistory((current) => [
        result,
        ...current.filter((item) => item.id !== result.id),
      ].slice(0, backtestHistoryLimit))
    } catch (error) {
      const failure = buildBacktestFailureState(request, error)
      setCurrentResult(failure.currentResult)
      setRunError(failure.error)
    } finally {
      setIsLoading(false)
    }
  }

  const runBacktest = (event) => {
    event.preventDefault()
    if (Object.keys(validateBacktestConfig(config)).length || !selectedAsset) return
    executeBacktest(createBacktestRunRequest(config, selectedAsset))
  }

  const retryBacktest = () => {
    if (!runError?.request) return
    executeBacktest(runError.request)
  }

  const reopenResult = (result) => {
    setIsLoading(false)
    setRunError(null)
    setConfig({ ...createDefaultBacktestConfig(), ...result.config })
    setSelectedAssetOverride(normalizeSecuritySearchOption(result.asset))
    setCurrentResult(result)
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
    if (nextResult) {
      setConfig({ ...createDefaultBacktestConfig(), ...nextResult.config })
      setSelectedAssetOverride(normalizeSecuritySearchOption(nextResult.asset))
    } else {
      setSelectedAssetOverride(null)
    }
  }

  return (
    <main className="main-content backtest-page-main">
      <section className="backtest-page-intro" aria-label="Backtest overview">
        <strong>Historical Strategy Simulation</strong>
        <span>Real historical-data backtest using stored daily OHLCV prices and the Django backtest API.</span>
      </section>

      <BacktestConfiguration
        assets={assets}
        allowedBenchmarks={availableBenchmarkSymbols}
        strategies={backtestStrategies}
        selectedAsset={selectedAsset}
        selectedBenchmark={selectedBenchmark}
        selectedStrategy={selectedStrategy}
        config={config}
        errors={errors}
        isAssetsLoading={isAssetsLoading}
        isLoading={isLoading}
        onChange={updateConfig}
        onSelectAsset={selectAsset}
        onSubmit={runBacktest}
      />

      {runError && (
        <section className="backtest-card backtest-state-card is-error" role="alert">
          <span className="backtest-state-icon" aria-hidden="true"><Icon name="strategy" /></span>
          <h2>Backtest request failed for {runError.assetSymbol}.</h2>
          <p>{runError.message}</p>
          {(runError.details?.required_rows || runError.details?.required_warmup_rows) && (
            <p>
              Required warm-up rows: {runError.details.required_rows ?? runError.details.required_warmup_rows}.{' '}
              {runError.details.symbol
                ? `${runError.details.symbol} available: ${runError.details.available_rows ?? 0}.`
                : `Asset available: ${runError.details.asset?.available_rows ?? 0}. Benchmark available: ${runError.details.benchmark?.available_rows ?? 0}.`}
            </p>
          )}
          {runError.details?.first_available_date && (
            <p>
              First available date: {runError.details.first_available_date}. Requested warm-up start:{' '}
              {runError.details.requested_warmup_start || 'unavailable'}.
            </p>
          )}
          <button type="button" className="secondary-button" onClick={retryBacktest}>
            Retry {runError.assetSymbol}
          </button>
        </section>
      )}

      <div className="backtest-result-region">
        {isLoading ? (
          <section className="backtest-card backtest-state-card" aria-live="polite" aria-busy="true">
            <i className="backtest-loading-spinner is-large" aria-hidden="true" />
            <h2>Running Backtest...</h2>
            <p>Calculating benchmark regime, ATR-sized Core and Swing layers, comparisons and trade history.</p>
          </section>
        ) : currentResult ? (
          <BacktestResults result={currentResult} />
        ) : !runError ? (
          <section className="backtest-card backtest-state-card" aria-labelledby="backtest-empty-title">
            <span className="backtest-state-icon" aria-hidden="true"><Icon name="strategy" /></span>
            <h2 id="backtest-empty-title">No backtest result selected.</h2>
            <p>Run a valid Market-Regime Core and Swing configuration, or reopen a saved real backtest result.</p>
          </section>
        ) : null}
      </div>

      <BacktestHistory history={history} onReopen={reopenResult} onDelete={deleteResult} />
    </main>
  )
}
