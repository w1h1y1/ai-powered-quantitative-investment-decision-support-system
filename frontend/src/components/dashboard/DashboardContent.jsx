import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../Icon'
import { marketDataApi } from '../../services/marketDataApi'
import { securityApi } from '../../services/securityApi'
import MarketSummary from './MarketSummary'
import PortfolioSummary from './PortfolioSummary'
import PriceChart from './PriceChart'
import TechnicalIndicators from './TechnicalIndicators'
import Watchlist from './Watchlist'
import {
  buildDashboardPriceChart,
  buildMarketDataRequestParams,
  createDefaultCustomMarketDataRange,
  dashboardMarketDataRanges,
  filterSecurityOptions,
  getActiveSecurities,
  getTodayDateInputValue,
  isCustomMarketDataRange,
  normalizeMarketData,
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
          <span>Daily OHLCV from market-data API</span>
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
  if (error?.status === 503) {
    return 'Daily market data is temporarily unavailable. Please try again later.'
  }
  return 'Unable to load daily market data. Please try again.'
}

export default function DashboardContent({ data, onOpenWatchlist }) {
  const [securities, setSecurities] = useState([])
  const [selectedSecurityId, setSelectedSecurityId] = useState(() => readStoredSecurityId())
  const [selectedRange, setSelectedRange] = useState(dashboardMarketDataRanges[0])
  const [customRange, setCustomRange] = useState(() => createDefaultCustomMarketDataRange())
  const [customRangeDraft, setCustomRangeDraft] = useState(() => createDefaultCustomMarketDataRange())
  const [securityQuery, setSecurityQuery] = useState('')
  const [isSecurityLoading, setIsSecurityLoading] = useState(true)
  const [securityError, setSecurityError] = useState('')
  const [marketData, setMarketData] = useState(null)
  const [isMarketDataLoading, setIsMarketDataLoading] = useState(false)
  const [marketDataError, setMarketDataError] = useState('')
  const marketDataRequestIdRef = useRef(0)

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

    marketDataApi.daily(buildMarketDataRequestParams({
      security: selectedSecurity,
      range: selectedRange,
      customRange,
    }))
      .then((response) => {
        if (
          isMounted
          && shouldApplyMarketDataResponse(marketDataRequestIdRef.current, requestId)
        ) {
          setMarketData(normalizeMarketData(response))
        }
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
  }, [customRange, customRangeMaxDate, selectedRange, selectedSecurity])

  const selectedPriceChart = useMemo(
    () => selectedSecurity
      ? buildDashboardPriceChart({
        security: selectedSecurity,
        marketData,
        range: selectedRange,
        isLoading: isMarketDataLoading,
        error: marketDataError,
      })
      : data.priceChart,
    [data.priceChart, isMarketDataLoading, marketData, marketDataError, selectedRange, selectedSecurity],
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

  const applyCustomRange = () => {
    const validationError = validateCustomMarketDataRange(customRangeDraft, customRangeMaxDate)
    if (validationError) return

    setCustomRange(customRangeDraft)
    setSelectedRange('Custom')
  }

  return (
    <main className="main-content dashboard-main">
      <MarketSummary items={data.marketSummary} />

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
            onCustomRangeApply={applyCustomRange}
            onCustomRangeChange={updateCustomRangeDraft}
            selectedRange={selectedRange}
            onRangeChange={setSelectedRange}
          />
          <TechnicalIndicators indicators={data.technicalIndicators} />
          <Watchlist items={data.watchlist} onViewAll={onOpenWatchlist} />
          <PortfolioSummary portfolio={data.portfolioSummary} />
        </div>
      )}
    </main>
  )
}
