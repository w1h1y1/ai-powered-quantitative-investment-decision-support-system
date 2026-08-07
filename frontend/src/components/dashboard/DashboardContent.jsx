import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../Icon'
import { marketDataApi } from '../../services/marketDataApi'
import { portfolioApi } from '../../services/portfolioApi'
import { securityApi } from '../../services/securityApi'
import {
  buildDashboardWatchlistItems,
  loadUserWatchlistData,
  watchlistDataChangedEventName,
} from '../../services/watchlistDataService'
import { normalizePortfolioSummary } from '../portfolio/portfolioSummaryModel'
import MarketSummary from './MarketSummary'
import PortfolioSummary from './PortfolioSummary'
import PriceChart from './PriceChart'
import TechnicalIndicators from './TechnicalIndicators'
import Watchlist from './Watchlist'
import {
  buildDashboardPriceChart,
  buildDashboardTechnicalIndicators,
  buildMarketDataRequestParams,
  createDefaultCustomMarketDataRange,
  dashboardMarketDataRanges,
  filterSecurityOptions,
  getActiveSecurities,
  getDefaultMarketDataInterval,
  getMarketDataDebugSummary,
  getMarketSummaryDebugSummary,
  getTodayDateInputValue,
  isCustomMarketDataRange,
  marketDataResponseMatchesRequest,
  normalizeMarketData,
  normalizeMarketSummary,
  readStoredSecurityId,
  resolveSelectedSecurityId,
  shouldApplyMarketDataResponse,
  validateCustomMarketDataRange,
  writeStoredSecurityId,
} from './dashboardSecurityModel'

function getSecurityLoadMessage(error) {
  if (error?.status === 401 || error?.status === 403) {
    return 'Your session has expired. Please sign in again.'
  }

  return 'Unable to load securities. Please try again.'
}

function DashboardSecurityState({ actionLabel, children, onAction, tone = '' }) {
  return (
    <section className={`dashboard-panel dashboard-security-state ${tone}`.trim()}>
      {children}
      {actionLabel && onAction && (
        <button className="panel-action" type="button" onClick={onAction}>{actionLabel}</button>
      )}
    </section>
  )
}

function SecuritySelectorPanel({
  filteredSecurities,
  onQueryChange,
  onSecurityChange,
  query,
  selectedSecurity,
  selectedSecurityId,
  securities,
}) {
  const selectOptions = useMemo(() => {
    if (!selectedSecurity) return filteredSecurities
    if (filteredSecurities.some((security) => String(security.id) === selectedSecurityId)) {
      return filteredSecurities
    }
    return [selectedSecurity, ...filteredSecurities]
  }, [filteredSecurities, selectedSecurity, selectedSecurityId])

  return (
    <section className="dashboard-panel dashboard-security-panel" aria-labelledby="dashboard-security-title">
      <div className="panel-header dashboard-security-header">
        <div>
          <p>Security universe</p>
          <h2 id="dashboard-security-title">{selectedSecurity.symbol}</h2>
          <span>{selectedSecurity.name}</span>
        </div>
        <div className="dashboard-security-source" aria-label="Dashboard data sources">
          <strong>Security API</strong>
          <span>OHLCV from market-data API</span>
        </div>
      </div>

      <div className="dashboard-security-controls">
        <label className="dashboard-security-search">
          <span>Search securities</span>
          <div>
            <Icon name="search" />
            <input
              type="search"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="Search symbol or company"
              autoComplete="off"
            />
          </div>
        </label>

        <label className="dashboard-security-select">
          <span>Selected security</span>
          <select value={selectedSecurityId} onChange={(event) => onSecurityChange(event.target.value)}>
            {selectOptions.map((security) => (
              <option key={security.id} value={security.id}>
                {security.symbol} - {security.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <dl className="dashboard-security-basics">
        <div>
          <dt>Symbol</dt>
          <dd>{selectedSecurity.symbol}</dd>
        </div>
        <div>
          <dt>Name</dt>
          <dd>{selectedSecurity.name}</dd>
        </div>
        <div>
          <dt>Asset Type</dt>
          <dd>{selectedSecurity.assetType}</dd>
        </div>
        <div>
          <dt>Exchange</dt>
          <dd>{selectedSecurity.exchange}</dd>
        </div>
        <div>
          <dt>Currency</dt>
          <dd>{selectedSecurity.currency}</dd>
        </div>
      </dl>

      <p className="dashboard-security-count">
        Showing {filteredSecurities.length} of {securities.length} active securities from Django.
      </p>
    </section>
  )
}

function getMarketDataLoadMessage(error) {
  if (error?.status === 401 || error?.status === 403) {
    return 'Your session has expired. Please sign in again.'
  }
  if (error?.status === 0) {
    return 'Unable to connect to the server. Please try again later.'
  }
  if ([400, 404, 429, 503].includes(error?.status)) {
    return error?.message || 'Market data is temporarily unavailable. Please try again later.'
  }
  return 'Unable to load market data. Please try again.'
}

function getMarketSummaryLoadMessage(error) {
  if (error?.status === 401 || error?.status === 403) {
    return 'Your session has expired. Please sign in again.'
  }
  if (error?.status === 0) {
    return 'Unable to connect to the server. Please try again later.'
  }
  return 'Unable to load market summary. Please try again later.'
}

function getWatchlistLoadMessage(error) {
  if (error?.status === 401 || error?.status === 403) {
    return 'Your session has expired. Please sign in again.'
  }
  if (error?.status === 0) {
    return 'Unable to connect to the server. Please try again later.'
  }
  return error?.message || 'Unable to load your Watchlist.'
}

function getPortfolioLoadMessage(error) {
  if (error?.status === 401 || error?.status === 403) {
    return 'Your session has expired. Please sign in again.'
  }
  if (error?.status === 0) {
    return 'Unable to connect to the server. Please try again later.'
  }
  return error?.message || 'Unable to load Portfolio Summary.'
}

export default function DashboardContent({ data, onOpenPortfolio, onOpenWatchlist }) {
  const [marketSummary, setMarketSummary] = useState(() => normalizeMarketSummary({ items: [] }))
  const [isMarketSummaryLoading, setIsMarketSummaryLoading] = useState(true)
  const [marketSummaryError, setMarketSummaryError] = useState('')
  const [securities, setSecurities] = useState([])
  const [selectedSecurityId, setSelectedSecurityId] = useState(() => readStoredSecurityId())
  const [selectedRange, setSelectedRange] = useState(dashboardMarketDataRanges[0])
  const [selectedInterval, setSelectedInterval] = useState(() => getDefaultMarketDataInterval(dashboardMarketDataRanges[0]))
  const [customRange, setCustomRange] = useState(() => createDefaultCustomMarketDataRange())
  const [customRangeDraft, setCustomRangeDraft] = useState(() => createDefaultCustomMarketDataRange())
  const [isCustomRangeOpen, setIsCustomRangeOpen] = useState(false)
  const [securityQuery, setSecurityQuery] = useState('')
  const [isSecurityLoading, setIsSecurityLoading] = useState(true)
  const [securityError, setSecurityError] = useState('')
  const [marketData, setMarketData] = useState(null)
  const [isMarketDataLoading, setIsMarketDataLoading] = useState(false)
  const [marketDataError, setMarketDataError] = useState('')
  const [watchlistItems, setWatchlistItems] = useState([])
  const [isWatchlistLoading, setIsWatchlistLoading] = useState(true)
  const [watchlistError, setWatchlistError] = useState('')
  const [portfolioSummary, setPortfolioSummary] = useState(null)
  const [isPortfolioSummaryLoading, setIsPortfolioSummaryLoading] = useState(true)
  const [portfolioSummaryError, setPortfolioSummaryError] = useState('')
  const marketSummaryRequestIdRef = useRef(0)
  const marketDataRequestIdRef = useRef(0)
  const watchlistRequestIdRef = useRef(0)
  const portfolioSummaryRequestIdRef = useRef(0)

  useEffect(() => {
    let isMounted = true
    const requestId = marketSummaryRequestIdRef.current + 1
    marketSummaryRequestIdRef.current = requestId

    setIsMarketSummaryLoading(true)
    setMarketSummaryError('')

    marketDataApi.summary()
      .then((response) => {
        if (!isMounted || marketSummaryRequestIdRef.current !== requestId) return
        const normalizedMarketSummary = normalizeMarketSummary(response)
        if (import.meta.env.DEV) {
          console.debug('[market-summary]', getMarketSummaryDebugSummary(response, normalizedMarketSummary))
        }
        setMarketSummary(normalizedMarketSummary)
      })
      .catch((error) => {
        if (!isMounted || marketSummaryRequestIdRef.current !== requestId) return
        setMarketSummary(normalizeMarketSummary({ items: [] }))
        setMarketSummaryError(getMarketSummaryLoadMessage(error))
      })
      .finally(() => {
        if (isMounted && marketSummaryRequestIdRef.current === requestId) {
          setIsMarketSummaryLoading(false)
        }
      })

    return () => {
      isMounted = false
    }
  }, [])

  const loadDashboardWatchlist = useCallback(async ({ force = false } = {}) => {
    const requestId = watchlistRequestIdRef.current + 1
    watchlistRequestIdRef.current = requestId

    setIsWatchlistLoading(true)
    setWatchlistError('')

    try {
      const response = await loadUserWatchlistData({ force })
      if (watchlistRequestIdRef.current !== requestId) return
      setWatchlistItems(buildDashboardWatchlistItems(response.selectedStocks))
      setWatchlistError(response.quoteError && !response.selectedStocks.length ? response.quoteError : '')
    } catch (error) {
      if (watchlistRequestIdRef.current !== requestId) return
      setWatchlistItems([])
      setWatchlistError(getWatchlistLoadMessage(error))
    } finally {
      if (watchlistRequestIdRef.current === requestId) {
        setIsWatchlistLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    loadDashboardWatchlist()

    const handleWatchlistChanged = () => {
      loadDashboardWatchlist({ force: true })
    }

    window.addEventListener(watchlistDataChangedEventName, handleWatchlistChanged)
    return () => {
      window.removeEventListener(watchlistDataChangedEventName, handleWatchlistChanged)
    }
  }, [loadDashboardWatchlist])

  const loadDashboardPortfolioSummary = useCallback(async () => {
    const requestId = portfolioSummaryRequestIdRef.current + 1
    portfolioSummaryRequestIdRef.current = requestId

    setIsPortfolioSummaryLoading(true)
    setPortfolioSummaryError('')

    try {
      const response = await portfolioApi.summary()
      if (portfolioSummaryRequestIdRef.current !== requestId) return
      setPortfolioSummary(normalizePortfolioSummary(response))
    } catch (error) {
      if (portfolioSummaryRequestIdRef.current !== requestId) return
      setPortfolioSummary(null)
      setPortfolioSummaryError(getPortfolioLoadMessage(error))
    } finally {
      if (portfolioSummaryRequestIdRef.current === requestId) {
        setIsPortfolioSummaryLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    loadDashboardPortfolioSummary()
  }, [loadDashboardPortfolioSummary])

  const loadSecurities = useCallback(async () => {
    setIsSecurityLoading(true)
    setSecurityError('')

    try {
      const response = await securityApi.list()
      setSecurities(getActiveSecurities(response))
    } catch (error) {
      setSecurities([])
      setSecurityError(getSecurityLoadMessage(error))
    } finally {
      setIsSecurityLoading(false)
    }
  }, [])

  useEffect(() => {
    loadSecurities()
  }, [loadSecurities])

  useEffect(() => {
    if (isSecurityLoading || securityError) return

    const resolvedSecurityId = resolveSelectedSecurityId({
      securities,
      currentSecurityId: selectedSecurityId,
      storedSecurityId: readStoredSecurityId(),
    })
    if (resolvedSecurityId !== selectedSecurityId) {
      setSelectedSecurityId(resolvedSecurityId)
    }
    writeStoredSecurityId(resolvedSecurityId)
  }, [isSecurityLoading, securities, securityError, selectedSecurityId])

  const selectedSecurity = useMemo(
    () => securities.find((security) => String(security.id) === selectedSecurityId) ?? null,
    [securities, selectedSecurityId],
  )
  const filteredSecurities = useMemo(
    () => filterSecurityOptions(securities, securityQuery),
    [securities, securityQuery],
  )
  const customRangeMaxDate = getTodayDateInputValue()
  const customRangeDraftError = useMemo(
    () => validateCustomMarketDataRange(customRangeDraft, customRangeMaxDate),
    [customRangeDraft, customRangeMaxDate],
  )

  useEffect(() => {
    if (!selectedSecurity) {
      marketDataRequestIdRef.current += 1
      setMarketData(null)
      setMarketDataError('')
      setIsMarketDataLoading(false)
      return
    }

    let isMounted = true
    const requestId = marketDataRequestIdRef.current + 1
    marketDataRequestIdRef.current = requestId
    const activeCustomRangeError = isCustomMarketDataRange(selectedRange)
      ? validateCustomMarketDataRange(customRange, customRangeMaxDate)
      : ''
    if (activeCustomRangeError) {
      setMarketData(null)
      setMarketDataError(activeCustomRangeError)
      setIsMarketDataLoading(false)
      return () => {
        isMounted = false
      }
    }

    setIsMarketDataLoading(true)
    setMarketDataError('')
    setMarketData(null)

    const requestParams = buildMarketDataRequestParams({
      security: selectedSecurity,
      range: selectedRange,
      customRange,
      interval: selectedInterval,
    })

    marketDataApi.daily(requestParams)
      .then((response) => {
        if (
          !isMounted
          || !shouldApplyMarketDataResponse(marketDataRequestIdRef.current, requestId)
        ) return

        if (!marketDataResponseMatchesRequest(response, requestParams)) {
          setMarketData(null)
          setMarketDataError('Received market data did not match the selected security or interval. Please try again.')
          return
        }

        const normalizedMarketData = normalizeMarketData(response)
        if (import.meta.env.DEV) {
          const debugPriceChart = buildDashboardPriceChart({
            security: selectedSecurity,
            marketData: normalizedMarketData,
            range: selectedRange,
            requestedInterval: selectedInterval,
          })
          console.debug('[market-data]', getMarketDataDebugSummary({
            request: requestParams,
            response,
            marketData: normalizedMarketData,
            chart: debugPriceChart,
          }))
        }
        setMarketData(normalizedMarketData)
      })
      .catch((error) => {
        if (
          !isMounted
          || !shouldApplyMarketDataResponse(marketDataRequestIdRef.current, requestId)
        ) return
        setMarketData(null)
        setMarketDataError(getMarketDataLoadMessage(error))
      })
      .finally(() => {
        if (
          isMounted
          && shouldApplyMarketDataResponse(marketDataRequestIdRef.current, requestId)
        ) {
          setIsMarketDataLoading(false)
        }
      })

    return () => {
      isMounted = false
    }
  }, [customRange, customRangeMaxDate, selectedInterval, selectedRange, selectedSecurity])

  const selectedPriceChart = useMemo(
    () => selectedSecurity
      ? buildDashboardPriceChart({
        security: selectedSecurity,
        marketData,
        range: selectedRange,
        requestedInterval: selectedInterval,
        isLoading: isMarketDataLoading,
        error: marketDataError,
      })
      : data.priceChart,
    [data.priceChart, isMarketDataLoading, marketData, marketDataError, selectedInterval, selectedRange, selectedSecurity],
  )
  const selectedTechnicalIndicators = useMemo(
    () => buildDashboardTechnicalIndicators(selectedPriceChart),
    [selectedPriceChart],
  )

  const updateSelectedSecurity = (securityId) => {
    setSelectedSecurityId(securityId)
    writeStoredSecurityId(securityId)
  }

  const updateCustomRangeDraft = (field, value) => {
    setCustomRangeDraft((currentRange) => ({
      ...currentRange,
      [field]: value,
    }))
  }

  const updateSelectedRange = (range) => {
    if (isCustomMarketDataRange(range)) {
      setCustomRangeDraft(customRange)
      setIsCustomRangeOpen(true)
      return
    }

    setIsCustomRangeOpen(false)
    setSelectedRange(range)
    setSelectedInterval(getDefaultMarketDataInterval(range))
  }

  const updateSelectedInterval = (interval) => {
    setSelectedInterval(interval)
    setCustomRangeDraft((currentRange) => ({
      ...currentRange,
      interval,
    }))
    if (isCustomMarketDataRange(selectedRange)) {
      setCustomRange((currentRange) => ({
        ...currentRange,
        interval,
      }))
    }
  }

  const cancelCustomRange = () => {
    setCustomRangeDraft(customRange)
    setIsCustomRangeOpen(false)
  }

  const applyCustomRange = () => {
    const validationError = validateCustomMarketDataRange(customRangeDraft, customRangeMaxDate)
    if (validationError) return

    setCustomRange(customRangeDraft)
    setSelectedInterval(customRangeDraft.interval)
    setSelectedRange('Custom')
    setIsCustomRangeOpen(false)
  }

  return (
    <main className="main-content dashboard-main">
      <MarketSummary
        error={marketSummaryError}
        isLoading={isMarketSummaryLoading}
        items={marketSummary.items}
        lastUpdatedLabel={marketSummary.lastUpdatedLabel}
        statusLabel={marketSummary.statusLabel}
      />

      {isSecurityLoading ? (
        <DashboardSecurityState>
          <p>Security API</p>
          <h2>Loading securities...</h2>
          <span>Fetching the available Security records from Django.</span>
        </DashboardSecurityState>
      ) : securityError ? (
        <DashboardSecurityState actionLabel="Retry" onAction={loadSecurities} tone="is-error">
          <p>Security API</p>
          <h2>Securities request failed.</h2>
          <span>{securityError}</span>
        </DashboardSecurityState>
      ) : selectedSecurity ? (
        <SecuritySelectorPanel
          filteredSecurities={filteredSecurities}
          onQueryChange={setSecurityQuery}
          onSecurityChange={updateSelectedSecurity}
          query={securityQuery}
          selectedSecurity={selectedSecurity}
          selectedSecurityId={selectedSecurityId}
          securities={securities}
        />
      ) : (
        <DashboardSecurityState tone="is-empty">
          <p>Security API</p>
          <h2>No active securities.</h2>
          <span>Add active Security records in Django before selecting a dashboard instrument.</span>
        </DashboardSecurityState>
      )}

      {selectedSecurity && (
        <div className="dashboard-grid">
          <PriceChart
            chart={selectedPriceChart}
            customRange={customRangeDraft}
            customRangeError={customRangeDraftError}
            customRangeMaxDate={customRangeMaxDate}
            isCustomRangeOpen={isCustomRangeOpen}
            onCustomRangeApply={applyCustomRange}
            onCustomRangeCancel={cancelCustomRange}
            onCustomRangeChange={updateCustomRangeDraft}
            onIntervalChange={updateSelectedInterval}
            selectedRange={selectedRange}
            selectedInterval={selectedInterval}
            onRangeChange={updateSelectedRange}
          />
          <TechnicalIndicators indicators={selectedTechnicalIndicators} />
          <Watchlist
            error={watchlistError}
            isLoading={isWatchlistLoading}
            items={watchlistItems}
            onRetry={() => loadDashboardWatchlist({ force: true })}
            onViewAll={onOpenWatchlist}
          />
          <PortfolioSummary
            error={portfolioSummaryError}
            isLoading={isPortfolioSummaryLoading}
            onRetry={loadDashboardPortfolioSummary}
            portfolio={portfolioSummary}
            onViewDetails={onOpenPortfolio}
          />
        </div>
      )}
    </main>
  )
}
