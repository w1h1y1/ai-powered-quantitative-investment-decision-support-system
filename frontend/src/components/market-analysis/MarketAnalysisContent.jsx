import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  buildDashboardIndicators,
  buildMarketDataRequestParams,
  createDefaultCustomMarketDataRange,
  dashboardMarketDataIntervals,
  dashboardMarketDataRanges,
  formatDashboardDateLabel,
  getActiveSecurities,
  getDefaultCustomMarketDataInterval,
  getDefaultMarketDataInterval,
  getTodayDateInputValue,
  isCustomMarketDataRange,
  marketDataResponseMatchesRequest,
  normalizeDashboardVisibleWindow,
  normalizeMarketData,
  shouldApplyMarketDataResponse,
  validateCustomMarketDataRange,
} from '../dashboard/dashboardSecurityModel'
import { marketDataApi } from '../../services/marketDataApi'
import { marketRegimeApi } from '../../services/marketRegimeApi'
import { securityApi } from '../../services/securityApi'
import { strategyEvaluationApi } from '../../services/strategyEvaluationApi'
import IndicatorOverlayControls from './IndicatorOverlayControls'
import MacdChart from './MacdChart'
import MarketControls from './MarketControls'
import MarketPriceChart from './MarketPriceChart'
import MarketRegimePanel from './MarketRegimePanel'
import RsiChart from './RsiChart'
import StrategyEvaluationPanel from './StrategyEvaluationPanel'
import TechnicalSummary from './TechnicalSummary'
import VolumeChart from './VolumeChart'
import {
  getMarketRegimePanelState,
  isCurrentMarketRegimeRequest,
  normalizeMarketRegime,
} from './marketRegimeModel'
import {
  getStrategyEvaluationPanelState,
  isCurrentStrategyEvaluationRequest,
  normalizeStrategyEvaluation,
} from './strategyEvaluationModel'

const marketOverlayOptions = [
  { id: 'ma5', label: 'MA5', fullName: 'Moving Average 5', type: 'ma', period: 5 },
  { id: 'ma10', label: 'MA10', fullName: 'Moving Average 10', type: 'ma', period: 10 },
  { id: 'ma20', label: 'MA20', fullName: 'Moving Average 20', type: 'ma', period: 20 },
  { id: 'ema12', label: 'EMA12', fullName: 'Exponential Moving Average 12', type: 'ema', period: 12 },
  {
    id: 'bollinger20',
    label: 'Bollinger',
    legendLabel: 'Bollinger Bands (20, 2)',
    fullName: 'Bollinger Bands (20, 2)',
    type: 'bollinger',
    period: 20,
  },
]

function normalizeSymbol(value) {
  return String(value ?? '').trim().toUpperCase()
}

function getErrorMessage(error, fallback) {
  return error?.message || fallback
}

function buildMarketAnalysisStock(security) {
  return {
    id: security.id,
    symbol: security.symbol,
    company: security.name,
    exchange: security.exchange,
    currency: security.currency,
    stats: {
      marketCap: 'N/A',
    },
  }
}

function getCandleTimestamp(candle) {
  const timestamp = Date.parse(candle?.date)
  return Number.isFinite(timestamp) ? timestamp : null
}

function buildMarketAnalysisCandle(candle, index) {
  return {
    id: `${candle.date || 'candle'}-${index}`,
    timestamp: getCandleTimestamp(candle) ?? index,
    date: candle.date,
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close,
    volume: candle.volume,
  }
}

function buildMarketAnalysisLabels(candles, range, interval) {
  const labelCount = Math.min(5, candles.length)
  return labelCount > 1
    ? Array.from({ length: labelCount }, (_, index) => {
      const candleIndex = Math.round((index / (labelCount - 1)) * (candles.length - 1))
      return formatDashboardDateLabel(candles[candleIndex]?.date, interval, range)
    })
    : []
}

function buildMarketAnalysisHistory(marketData, range, interval) {
  const sourceCandles = marketData?.visibleData ?? marketData?.candles ?? []
  const warmupCandles = marketData?.warmupCandles ?? []
  const candles = sourceCandles.map(buildMarketAnalysisCandle)
  const normalizedWarmupCandles = warmupCandles.map(buildMarketAnalysisCandle)
  const effectiveInterval = marketData?.interval ?? interval
  const indicators = buildDashboardIndicators(candles, normalizedWarmupCandles)

  return {
    candles,
    indicators,
    labels: buildMarketAnalysisLabels(candles, range, effectiveInterval),
    opens: candles.map((candle) => candle.open),
    highs: candles.map((candle) => candle.high),
    lows: candles.map((candle) => candle.low),
    closes: candles.map((candle) => candle.close),
    volumes: candles.map((candle) => candle.volume),
  }
}

function sliceMarketAnalysisHistory(history, window, range, interval) {
  const candles = history.candles.slice(window.start, window.end + 1)
  const indicators = history.indicators.slice(window.start, window.end + 1)

  return {
    candles,
    indicators,
    labels: buildMarketAnalysisLabels(candles, range, interval),
    opens: candles.map((candle) => candle.open),
    highs: candles.map((candle) => candle.high),
    lows: candles.map((candle) => candle.low),
    closes: candles.map((candle) => candle.close),
    volumes: candles.map((candle) => candle.volume),
  }
}

function MarketAnalysisState({ actionLabel, children, onAction, tone = '' }) {
  return (
    <section className={`market-panel market-analysis-state ${tone}`.trim()} aria-live="polite">
      <p>{children}</p>
      {actionLabel && onAction && (
        <button type="button" onClick={onAction}>{actionLabel}</button>
      )}
    </section>
  )
}

export default function MarketAnalysisContent({
  selectedSymbol,
  onSelectedSymbolChange,
}) {
  const [securities, setSecurities] = useState([])
  const [isSecurityLoading, setIsSecurityLoading] = useState(true)
  const [securityError, setSecurityError] = useState('')
  const [selectedRange, setSelectedRange] = useState(dashboardMarketDataRanges[0])
  const [selectedInterval, setSelectedInterval] = useState(getDefaultMarketDataInterval(dashboardMarketDataRanges[0]))
  const [customRange, setCustomRange] = useState(() => createDefaultCustomMarketDataRange())
  const [marketData, setMarketData] = useState(null)
  const [isMarketDataLoading, setIsMarketDataLoading] = useState(false)
  const [marketDataError, setMarketDataError] = useState('')
  const [marketDataReloadKey, setMarketDataReloadKey] = useState(0)
  const [marketRegimeRequest, setMarketRegimeRequest] = useState({
    data: null,
    error: '',
    status: 'idle',
    symbol: '',
  })
  const [marketRegimeReloadKey, setMarketRegimeReloadKey] = useState(0)
  const [strategyEvaluationRequest, setStrategyEvaluationRequest] = useState({
    data: null,
    error: '',
    status: 'idle',
    symbol: '',
  })
  const [strategyEvaluationReloadKey, setStrategyEvaluationReloadKey] = useState(0)
  const [selectedOverlays, setSelectedOverlays] = useState(['ma5', 'ma10', 'ma20'])
  const [chartType, setChartType] = useState('candlestick')
  const [priceVisibleWindow, setPriceVisibleWindow] = useState(null)
  const [rsiVisibleWindow, setRsiVisibleWindow] = useState(null)
  const [volumeVisibleWindow, setVolumeVisibleWindow] = useState(null)
  const [macdVisibleWindow, setMacdVisibleWindow] = useState(null)
  const securityRequestIdRef = useRef(0)
  const marketDataRequestIdRef = useRef(0)
  const marketRegimeRequestIdRef = useRef(0)
  const strategyEvaluationRequestIdRef = useRef(0)

  const loadSecurities = useCallback(() => {
    const requestId = securityRequestIdRef.current + 1
    securityRequestIdRef.current = requestId
    setIsSecurityLoading(true)
    setSecurityError('')

    securityApi.list()
      .then((response) => {
        if (securityRequestIdRef.current !== requestId) return
        setSecurities(getActiveSecurities(response))
      })
      .catch((error) => {
        if (securityRequestIdRef.current !== requestId) return
        setSecurities([])
        setSecurityError(getErrorMessage(error, 'Unable to load securities.'))
      })
      .finally(() => {
        if (securityRequestIdRef.current === requestId) {
          setIsSecurityLoading(false)
        }
      })
  }, [])

  useEffect(() => {
    loadSecurities()
  }, [loadSecurities])

  const requestedSymbol = normalizeSymbol(selectedSymbol)
  const selectedSecurity = useMemo(() => {
    if (!securities.length) return null
    if (requestedSymbol) {
      return securities.find((security) => security.symbol === requestedSymbol) ?? null
    }
    return securities[0]
  }, [requestedSymbol, securities])
  const controlSecurity = selectedSecurity ?? securities[0] ?? null
  const controlSelectedSymbol = selectedSecurity?.symbol ?? requestedSymbol
  const selectedStock = selectedSecurity ? buildMarketAnalysisStock(selectedSecurity) : null
  const controlStocks = useMemo(() => securities.map(buildMarketAnalysisStock), [securities])
  const selectedSecuritySymbol = selectedSecurity?.symbol ?? ''
  const selectedSecurityId = selectedSecurity?.id ?? null
  const visibleMarketRegimeRequest = getMarketRegimePanelState(
    marketRegimeRequest,
    selectedSecuritySymbol,
  )
  const visibleStrategyEvaluationRequest = getStrategyEvaluationPanelState(
    strategyEvaluationRequest,
    selectedSecuritySymbol,
  )

  useEffect(() => {
    if (!selectedSecurity) return
    if (selectedSecurity.symbol !== requestedSymbol) {
      onSelectedSymbolChange(selectedSecurity.symbol)
    }
  }, [onSelectedSymbolChange, requestedSymbol, selectedSecurity])

  useEffect(() => {
    if (!selectedSecurity) {
      setMarketData(null)
      setMarketDataError('')
      setIsMarketDataLoading(false)
      return undefined
    }

    const effectiveCustomRange = isCustomMarketDataRange(selectedRange)
      ? { ...customRange, interval: selectedInterval }
      : customRange
    const validationError = isCustomMarketDataRange(selectedRange)
      ? validateCustomMarketDataRange(effectiveCustomRange, getTodayDateInputValue())
      : ''

    if (validationError) {
      setMarketData(null)
      setMarketDataError(validationError)
      setIsMarketDataLoading(false)
      return undefined
    }

    const requestParams = buildMarketDataRequestParams({
      security: selectedSecurity,
      range: selectedRange,
      customRange: effectiveCustomRange,
      interval: selectedInterval,
    })
    const requestId = marketDataRequestIdRef.current + 1
    let ignore = false
    marketDataRequestIdRef.current = requestId

    setIsMarketDataLoading(true)
    setMarketDataError('')

    marketDataApi.daily(requestParams)
      .then((response) => {
        if (ignore || !shouldApplyMarketDataResponse(marketDataRequestIdRef.current, requestId)) return
        if (!marketDataResponseMatchesRequest(response, requestParams)) {
          throw new Error('Market data response did not match the selected stock and time range.')
        }
        setMarketData(normalizeMarketData(response))
      })
      .catch((error) => {
        if (ignore || !shouldApplyMarketDataResponse(marketDataRequestIdRef.current, requestId)) return
        setMarketData(null)
        setMarketDataError(getErrorMessage(error, 'Unable to load market data.'))
      })
      .finally(() => {
        if (!ignore && shouldApplyMarketDataResponse(marketDataRequestIdRef.current, requestId)) {
          setIsMarketDataLoading(false)
        }
      })

    return () => {
      ignore = true
    }
  }, [customRange, marketDataReloadKey, selectedInterval, selectedRange, selectedSecurity])

  useEffect(() => {
    if (!selectedSecuritySymbol) {
      marketRegimeRequestIdRef.current += 1
      setMarketRegimeRequest({ data: null, error: '', status: 'idle', symbol: '' })
      return undefined
    }

    const requestId = marketRegimeRequestIdRef.current + 1
    let ignore = false
    marketRegimeRequestIdRef.current = requestId
    setMarketRegimeRequest({
      data: null,
      error: '',
      status: 'loading',
      symbol: selectedSecuritySymbol,
    })

    marketRegimeApi.get({ symbol: selectedSecuritySymbol })
      .then((response) => {
        if (ignore || !isCurrentMarketRegimeRequest(marketRegimeRequestIdRef.current, requestId)) return
        setMarketRegimeRequest({
          data: normalizeMarketRegime(response, selectedSecuritySymbol, selectedSecurityId),
          error: '',
          status: 'ready',
          symbol: selectedSecuritySymbol,
        })
      })
      .catch((error) => {
        if (ignore || !isCurrentMarketRegimeRequest(marketRegimeRequestIdRef.current, requestId)) return
        setMarketRegimeRequest({
          data: null,
          error: getErrorMessage(error, `Unable to load market regime for ${selectedSecuritySymbol}.`),
          status: 'error',
          symbol: selectedSecuritySymbol,
        })
      })

    return () => {
      ignore = true
    }
  }, [marketRegimeReloadKey, selectedSecurityId, selectedSecuritySymbol])

  useEffect(() => {
    if (!selectedSecuritySymbol) {
      strategyEvaluationRequestIdRef.current += 1
      setStrategyEvaluationRequest({ data: null, error: '', status: 'idle', symbol: '' })
      return undefined
    }

    const requestId = strategyEvaluationRequestIdRef.current + 1
    let ignore = false
    strategyEvaluationRequestIdRef.current = requestId
    setStrategyEvaluationRequest({
      data: null,
      error: '',
      status: 'loading',
      symbol: selectedSecuritySymbol,
    })

    strategyEvaluationApi.evaluate({ symbol: selectedSecuritySymbol })
      .then((response) => {
        if (ignore || !isCurrentStrategyEvaluationRequest(strategyEvaluationRequestIdRef.current, requestId)) return
        setStrategyEvaluationRequest({
          data: normalizeStrategyEvaluation(response, selectedSecuritySymbol),
          error: '',
          status: 'ready',
          symbol: selectedSecuritySymbol,
        })
      })
      .catch((error) => {
        if (ignore || !isCurrentStrategyEvaluationRequest(strategyEvaluationRequestIdRef.current, requestId)) return
        setStrategyEvaluationRequest({
          data: null,
          error: getErrorMessage(error, `Unable to load strategy evaluation for ${selectedSecuritySymbol}.`),
          status: 'error',
          symbol: selectedSecuritySymbol,
        })
      })

    return () => {
      ignore = true
    }
  }, [strategyEvaluationReloadKey, selectedSecurityId, selectedSecuritySymbol])

  const selectedHistory = useMemo(
    () => buildMarketAnalysisHistory(marketData, selectedRange, selectedInterval),
    [marketData, selectedInterval, selectedRange],
  )
  const marketDataKey = [
    selectedSecurity?.id ?? '',
    selectedRange,
    selectedInterval,
    marketData?.metadata?.firstDatetime ?? '',
    marketData?.metadata?.lastDatetime ?? '',
    marketData?.metadata?.count ?? 0,
  ].join('|')
  const normalizedPriceVisibleWindow = normalizeDashboardVisibleWindow(priceVisibleWindow, selectedHistory.candles.length)
  const normalizedRsiVisibleWindow = normalizeDashboardVisibleWindow(rsiVisibleWindow, selectedHistory.candles.length)
  const normalizedVolumeVisibleWindow = normalizeDashboardVisibleWindow(volumeVisibleWindow, selectedHistory.candles.length)
  const normalizedMacdVisibleWindow = normalizeDashboardVisibleWindow(macdVisibleWindow, selectedHistory.candles.length)
  const displayedHistory = useMemo(
    () => sliceMarketAnalysisHistory(selectedHistory, normalizedPriceVisibleWindow, selectedRange, selectedInterval),
    [
      normalizedPriceVisibleWindow.end,
      normalizedPriceVisibleWindow.start,
      selectedHistory,
      selectedInterval,
      selectedRange,
    ],
  )
  const rsiHistory = useMemo(
    () => sliceMarketAnalysisHistory(selectedHistory, normalizedRsiVisibleWindow, selectedRange, selectedInterval),
    [
      normalizedRsiVisibleWindow.end,
      normalizedRsiVisibleWindow.start,
      selectedHistory,
      selectedInterval,
      selectedRange,
    ],
  )
  const volumeHistory = useMemo(
    () => sliceMarketAnalysisHistory(selectedHistory, normalizedVolumeVisibleWindow, selectedRange, selectedInterval),
    [
      normalizedVolumeVisibleWindow.end,
      normalizedVolumeVisibleWindow.start,
      selectedHistory,
      selectedInterval,
      selectedRange,
    ],
  )
  const macdHistory = useMemo(
    () => sliceMarketAnalysisHistory(selectedHistory, normalizedMacdVisibleWindow, selectedRange, selectedInterval),
    [
      normalizedMacdVisibleWindow.end,
      normalizedMacdVisibleWindow.start,
      selectedHistory,
      selectedInterval,
      selectedRange,
    ],
  )
  const rangeLabel = selectedRange === 'Custom' && customRange
    ? `${customRange.startDate} - ${customRange.endDate}`
    : selectedRange
  const chartTimeframeLabel = `${rangeLabel} - ${selectedInterval} bars`
  const hasChartData = selectedHistory.candles.length > 1

  useEffect(() => {
    setPriceVisibleWindow(null)
    setRsiVisibleWindow(null)
    setVolumeVisibleWindow(null)
    setMacdVisibleWindow(null)
  }, [marketDataKey])

  const handleRangeChange = (nextRange) => {
    if (nextRange === selectedRange) return
    setSelectedRange(nextRange)
    setSelectedInterval(getDefaultMarketDataInterval(nextRange))
  }

  const handleCustomRangeApply = (dates) => {
    const interval = getDefaultCustomMarketDataInterval(dates.startDate, dates.endDate)
    setCustomRange({ ...dates, interval })
    setSelectedRange('Custom')
    setSelectedInterval(interval)
  }

  const handleIntervalChange = (nextInterval) => {
    setSelectedInterval(nextInterval)
    setCustomRange((current) => ({ ...current, interval: nextInterval }))
  }

  const retryMarketData = () => {
    setMarketDataReloadKey((current) => current + 1)
  }

  const retryMarketRegime = () => {
    setMarketRegimeRequest({
      data: null,
      error: '',
      status: 'loading',
      symbol: selectedSecuritySymbol,
    })
    setMarketRegimeReloadKey((current) => current + 1)
  }

  const retryStrategyEvaluation = () => {
    setStrategyEvaluationRequest({
      data: null,
      error: '',
      status: 'loading',
      symbol: selectedSecuritySymbol,
    })
    setStrategyEvaluationReloadKey((current) => current + 1)
  }

  const toggleOverlay = (overlayId) => {
    setSelectedOverlays((current) =>
      current.includes(overlayId)
        ? current.filter((id) => id !== overlayId)
        : [...current, overlayId],
    )
  }

  return (
    <main
      className="main-content market-analysis-main"
      data-chart-range={selectedRange}
      data-chart-interval={selectedInterval}
      data-chart-start={selectedRange === 'Custom' ? customRange?.startDate : undefined}
      data-chart-end={selectedRange === 'Custom' ? customRange?.endDate : undefined}
    >
      {controlSecurity && (
        <MarketControls
          stocks={controlStocks}
          selectedSymbol={controlSelectedSymbol}
          onStockChange={onSelectedSymbolChange}
          ranges={dashboardMarketDataRanges}
          selectedRange={selectedRange}
          onRangeChange={handleRangeChange}
          intervals={dashboardMarketDataIntervals}
          selectedInterval={selectedInterval}
          onIntervalChange={handleIntervalChange}
          chartType={chartType}
          onChartTypeChange={setChartType}
          customRange={customRange}
          onApplyCustomRange={handleCustomRangeApply}
          dataStatusLabel="Market Data API"
          dataStatusDetail={
            isMarketDataLoading
              ? 'Loading Twelve Data OHLCV...'
              : marketData?.isStale
                ? 'Cached Twelve Data OHLCV via Django'
                : 'Twelve Data OHLCV via Django'
          }
        />
      )}

      {selectedSecurity && (
        <MarketRegimePanel
          symbol={selectedSecuritySymbol}
          regime={visibleMarketRegimeRequest.data}
          isLoading={visibleMarketRegimeRequest.status === 'loading'}
          error={visibleMarketRegimeRequest.status === 'error' ? visibleMarketRegimeRequest.error : ''}
          onRetry={retryMarketRegime}
        />
      )}

      {selectedSecurity && (
        <StrategyEvaluationPanel
          symbol={selectedSecuritySymbol}
          evaluation={visibleStrategyEvaluationRequest.data}
          isLoading={visibleStrategyEvaluationRequest.status === 'loading'}
          error={visibleStrategyEvaluationRequest.status === 'error' ? visibleStrategyEvaluationRequest.error : ''}
          onRetry={retryStrategyEvaluation}
        />
      )}

      <div className="market-analysis-grid">
        {isSecurityLoading && (
          <MarketAnalysisState>Loading available stocks from the Securities API...</MarketAnalysisState>
        )}
        {!isSecurityLoading && securityError && (
          <MarketAnalysisState actionLabel="Retry" onAction={loadSecurities} tone="is-error">
            {securityError}
          </MarketAnalysisState>
        )}
        {!isSecurityLoading && !securityError && securities.length === 0 && (
          <MarketAnalysisState>No active stocks are available from the Securities API.</MarketAnalysisState>
        )}
        {!isSecurityLoading && !securityError && requestedSymbol && !selectedSecurity && (
          <MarketAnalysisState tone="is-error">
            {requestedSymbol} is not available in the current Securities API response.
          </MarketAnalysisState>
        )}
        {selectedSecurity && isMarketDataLoading && (
          <MarketAnalysisState>Loading real OHLCV data for {selectedSecurity.symbol}...</MarketAnalysisState>
        )}
        {selectedSecurity && !isMarketDataLoading && marketDataError && (
          <MarketAnalysisState actionLabel="Retry" onAction={retryMarketData} tone="is-error">
            {marketDataError}
          </MarketAnalysisState>
        )}
        {selectedSecurity && !isMarketDataLoading && !marketDataError && !hasChartData && (
          <MarketAnalysisState>
            No usable OHLCV data returned for {selectedSecurity.symbol} and the selected time range.
          </MarketAnalysisState>
        )}

        {selectedStock && !isMarketDataLoading && !marketDataError && hasChartData && (
          <>
            <MarketPriceChart
              stock={selectedStock}
              history={displayedHistory}
              rangeLabel={rangeLabel}
              interval={selectedInterval}
              overlayOptions={marketOverlayOptions}
              selectedOverlays={selectedOverlays}
              chartType={chartType}
              fullCandleCount={selectedHistory.candles.length}
              visibleWindow={normalizedPriceVisibleWindow}
              onVisibleWindowChange={setPriceVisibleWindow}
              onVisibleWindowReset={() => setPriceVisibleWindow(null)}
            />
            <IndicatorOverlayControls
              history={displayedHistory}
              options={marketOverlayOptions}
              selectedOverlays={selectedOverlays}
              onToggle={toggleOverlay}
            />
            <RsiChart
              stock={selectedStock}
              history={rsiHistory}
              timeframeLabel={chartTimeframeLabel}
              fullCandleCount={selectedHistory.candles.length}
              visibleWindow={normalizedRsiVisibleWindow}
              onVisibleWindowChange={setRsiVisibleWindow}
              onVisibleWindowReset={() => setRsiVisibleWindow(null)}
            />
            <TechnicalSummary history={displayedHistory} />
            <VolumeChart
              stock={selectedStock}
              history={volumeHistory}
              rangeLabel={rangeLabel}
              interval={selectedInterval}
              fullCandleCount={selectedHistory.candles.length}
              visibleWindow={normalizedVolumeVisibleWindow}
              onVisibleWindowChange={setVolumeVisibleWindow}
              onVisibleWindowReset={() => setVolumeVisibleWindow(null)}
            />
            <MacdChart
              stock={selectedStock}
              history={macdHistory}
              timeframeLabel={chartTimeframeLabel}
              fullCandleCount={selectedHistory.candles.length}
              visibleWindow={normalizedMacdVisibleWindow}
              onVisibleWindowChange={setMacdVisibleWindow}
              onVisibleWindowReset={() => setMacdVisibleWindow(null)}
            />
          </>
        )}
      </div>
    </main>
  )
}
