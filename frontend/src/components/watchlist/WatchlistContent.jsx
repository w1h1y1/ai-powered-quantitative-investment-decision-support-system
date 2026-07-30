import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../Icon'
import Sparkline from '../dashboard/Sparkline'
import { securityApi } from '../../services/securityApi'
import { watchlistApi } from '../../services/watchlistApi'

const unavailableTrend = [0, 0]

function formatCurrency(value) {
  if (!Number.isFinite(value)) return 'N/A'

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

function formatSignedCurrency(value) {
  if (!Number.isFinite(value)) return 'N/A'

  const sign = value >= 0 ? '+' : '-'
  return `${sign}${formatCurrency(Math.abs(value))}`
}

function formatSignedPercent(value) {
  if (!Number.isFinite(value)) return 'N/A'

  const sign = value >= 0 ? '+' : '-'
  return `${sign}${Math.abs(value).toFixed(2)}%`
}

function getStatusTone(status) {
  if (status === 'Bullish' || status === 'Uptrend') return 'is-positive'
  if (status === 'Bearish' || status === 'Downtrend') return 'is-negative'
  if (status === 'Near Overbought' || status === 'Near Oversold') return 'is-warning'
  return 'is-neutral'
}

function parseSignedValue(value) {
  const parsed = Number(String(value ?? '').replace(/[^0-9.-]/g, ''))
  return Number.isFinite(parsed) ? parsed : null
}

function normalizeSecurity(security) {
  if (!security) return null

  return {
    id: security.id,
    symbol: security.symbol,
    company: security.name,
    assetType: security.asset_type,
    exchange: security.exchange,
    currency: security.currency,
    isActive: security.is_active !== false,
  }
}

function buildMarketLookup(stocks) {
  return new Map((stocks ?? []).map((stock) => [stock.symbol, stock]))
}

function buildWatchlistStock(security, marketLookup, itemId = null) {
  const normalizedSecurity = normalizeSecurity(security)
  if (!normalizedSecurity) return null

  const marketStock = marketLookup.get(normalizedSecurity.symbol)
  const dailyChange = parseSignedValue(marketStock?.change)
  const changePercent = parseSignedValue(marketStock?.percent)
  const direction = marketStock?.direction ?? 'neutral'

  return {
    ...normalizedSecurity,
    itemId,
    price: Number.isFinite(marketStock?.price) ? marketStock.price : null,
    dailyChange,
    changePercent,
    direction,
    trend: marketStock?.history?.['1M']?.['1D']?.closes?.slice(-18) ?? unavailableTrend,
    rsiStatus: marketStock?.indicators?.rsi?.signal ?? 'Neutral',
    macdStatus: marketStock?.indicators?.macd?.signal ?? 'Neutral',
    overallTrend: direction === 'up' ? 'Uptrend' : direction === 'down' ? 'Downtrend' : 'Sideways',
  }
}

function getWatchlistItemSecurity(item, securitiesById) {
  const nestedSecurity = item?.security
  if (!nestedSecurity) return null
  return securitiesById.get(nestedSecurity.id) ?? nestedSecurity
}

function getErrorMessage(error) {
  const data = error?.data
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    if (data.security_id) {
      const message = Array.isArray(data.security_id) ? data.security_id[0] : data.security_id
      return String(message)
    }
    if (data.watchlist) {
      const message = Array.isArray(data.watchlist) ? data.watchlist[0] : data.watchlist
      return String(message)
    }
  }

  return error?.message || 'Request failed. Please try again.'
}

function WatchlistStateCard({ actionLabel, children, icon = 'watchlist', onAction, tone = '' }) {
  return (
    <section className={`watchlist-empty-state watchlist-record-state ${tone}`.trim()}>
      <span className="watchlist-empty-icon" aria-hidden="true"><Icon name={icon} /></span>
      {children}
      {actionLabel && onAction && (
        <button type="button" onClick={onAction}>{actionLabel}</button>
      )}
    </section>
  )
}

export default function WatchlistContent({ stocks = [], onViewAnalysis }) {
  const [watchlist, setWatchlist] = useState(null)
  const [watchlistItems, setWatchlistItems] = useState([])
  const [securities, setSecurities] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [query, setQuery] = useState('')
  const [feedback, setFeedback] = useState(null)
  const [isAdding, setIsAdding] = useState(false)
  const [removingItemId, setRemovingItemId] = useState(null)
  const searchInputRef = useRef(null)

  const loadWatchlistData = useCallback(async () => {
    setIsLoading(true)
    setLoadError('')
    setFeedback(null)
    setWatchlist(null)
    setWatchlistItems([])
    setSecurities([])

    try {
      const [watchlistsResponse, securitiesResponse] = await Promise.all([
        watchlistApi.list(),
        securityApi.list(),
      ])
      const watchlists = Array.isArray(watchlistsResponse) ? watchlistsResponse : []
      const currentWatchlist = watchlists[0] ?? null
      setWatchlist(currentWatchlist)
      setSecurities(Array.isArray(securitiesResponse) ? securitiesResponse : [])

      if (currentWatchlist) {
        const itemsResponse = await watchlistApi.items(currentWatchlist.id)
        setWatchlistItems(Array.isArray(itemsResponse) ? itemsResponse : [])
      }
    } catch (error) {
      setLoadError(error.message || 'Request failed. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadWatchlistData()
  }, [loadWatchlistData])

  const marketLookup = useMemo(() => buildMarketLookup(stocks), [stocks])
  const securitiesById = useMemo(
    () => new Map(securities.map((security) => [security.id, security])),
    [securities],
  )
  const securityOptions = useMemo(
    () => securities
      .map(normalizeSecurity)
      .filter((security) => security?.isActive),
    [securities],
  )
  const trackedSecurityIds = useMemo(
    () => new Set(watchlistItems.map((item) => item.security?.id).filter(Boolean)),
    [watchlistItems],
  )
  const selectedStocks = useMemo(
    () => watchlistItems
      .map((item) => buildWatchlistStock(
        getWatchlistItemSecurity(item, securitiesById),
        marketLookup,
        item.id,
      ))
      .filter(Boolean),
    [marketLookup, securitiesById, watchlistItems],
  )

  const normalizedQuery = query.trim().toLowerCase()
  const searchResults = useMemo(() => {
    if (!normalizedQuery) return []

    return securityOptions.filter((security) =>
      security.symbol.toLowerCase().includes(normalizedQuery)
      || security.company.toLowerCase().includes(normalizedQuery),
    )
  }, [normalizedQuery, securityOptions])

  const resolvedSecurity = useMemo(() => {
    if (!normalizedQuery) return null

    const exactMatch = searchResults.find(
      (security) => security.symbol.toLowerCase() === normalizedQuery
        || security.company.toLowerCase() === normalizedQuery,
    )

    return exactMatch ?? (searchResults.length === 1 ? searchResults[0] : null)
  }, [normalizedQuery, searchResults])

  const isDuplicate = resolvedSecurity ? trackedSecurityIds.has(resolvedSecurity.id) : false
  const totalStocks = selectedStocks.length
  const gainers = selectedStocks.filter((stock) => stock.dailyChange > 0).length
  const decliners = selectedStocks.filter((stock) => stock.dailyChange < 0).length

  const updateQuery = (value) => {
    setQuery(value)
    setFeedback(null)
  }

  const handleAdd = async (event) => {
    event.preventDefault()

    if (!watchlist) {
      setFeedback({
        tone: 'error',
        message: 'Watchlist is unavailable. Please reload the page.',
      })
      return
    }

    if (!resolvedSecurity) {
      setFeedback({
        tone: 'error',
        message: searchResults.length > 1
          ? 'Select one security from the matching results.'
          : 'No matching security was found.',
      })
      return
    }

    if (trackedSecurityIds.has(resolvedSecurity.id)) {
      setFeedback({
        tone: 'error',
        message: `${resolvedSecurity.symbol} is already in your watchlist.`,
      })
      return
    }

    setIsAdding(true)
    try {
      const createdItem = await watchlistApi.createItem({
        watchlist: watchlist.id,
        security_id: resolvedSecurity.id,
      })
      setWatchlistItems((current) => (
        current.some((item) => item.id === createdItem.id)
          ? current
          : [createdItem, ...current]
      ))
      setQuery('')
      setFeedback({
        tone: 'success',
        message: `${resolvedSecurity.symbol} was added to your watchlist.`,
      })
      searchInputRef.current?.focus()
    } catch (error) {
      setFeedback({
        tone: 'error',
        message: getErrorMessage(error),
      })
    } finally {
      setIsAdding(false)
    }
  }

  const handleRemove = async (stock) => {
    const shouldRemove = window.confirm(`Remove ${stock.symbol} - ${stock.company} from your watchlist?`)
    if (!shouldRemove) return

    setRemovingItemId(stock.itemId)
    setFeedback(null)
    try {
      await watchlistApi.removeItem(stock.itemId)
      setWatchlistItems((current) => current.filter((item) => item.id !== stock.itemId))
      setFeedback({
        tone: 'success',
        message: `${stock.symbol} was removed from your watchlist.`,
      })
    } catch (error) {
      setFeedback({
        tone: 'error',
        message: getErrorMessage(error),
      })
    } finally {
      setRemovingItemId(null)
    }
  }

  const focusSearch = () => {
    searchInputRef.current?.focus()
  }

  const notice = isDuplicate
    ? { tone: 'error', message: `${resolvedSecurity.symbol} is already in your watchlist.` }
    : feedback
  const addButtonLabel = isAdding ? 'Adding...' : 'Add to Watchlist'

  if (isLoading) {
    return (
      <main className="main-content watchlist-page-main">
        <section className="watchlist-page-heading" aria-labelledby="watchlist-page-title">
          <div>
            <p>Personal market tracker</p>
            <h2 id="watchlist-page-title">Watchlist</h2>
            <span>Loading your saved Watchlist from the Django API.</span>
          </div>
        </section>
        <WatchlistStateCard>
          <h3>Loading Watchlist...</h3>
          <p>Your saved securities are being loaded from PostgreSQL.</p>
        </WatchlistStateCard>
      </main>
    )
  }

  if (loadError) {
    return (
      <main className="main-content watchlist-page-main">
        <section className="watchlist-page-heading" aria-labelledby="watchlist-page-title">
          <div>
            <p>Personal market tracker</p>
            <h2 id="watchlist-page-title">Watchlist</h2>
            <span>Unable to load your Watchlist record.</span>
          </div>
        </section>
        <WatchlistStateCard actionLabel="Retry" onAction={loadWatchlistData} tone="is-error">
          <h3>Watchlist request failed.</h3>
          <p>{loadError}</p>
        </WatchlistStateCard>
      </main>
    )
  }

  return (
    <main className="main-content watchlist-page-main">
      <section className="watchlist-page-heading" aria-labelledby="watchlist-page-title">
        <div>
          <p>Personal market tracker</p>
          <h2 id="watchlist-page-title">{watchlist?.name ?? 'Watchlist'}</h2>
          <span>Track selected securities and review their latest market and technical status.</span>
        </div>
        <div className="demo-data-status" aria-label="Watchlist data source">
          <strong>Watchlist API</strong>
          <span>Django records with demo pricing</span>
        </div>
      </section>

      <section className="watchlist-add-card" aria-labelledby="watchlist-add-title">
        <div className="watchlist-add-copy">
          <p>Security search</p>
          <h2 id="watchlist-add-title">Add a security</h2>
          <span>Search the available securities by ticker symbol or company name.</span>
        </div>

        <form className="watchlist-add-form" onSubmit={handleAdd}>
          <label className="watchlist-search-field">
            <span>Symbol or company</span>
            <div className="watchlist-search-input">
              <Icon name="search" />
              <input
                ref={searchInputRef}
                type="search"
                value={query}
                onChange={(event) => updateQuery(event.target.value)}
                placeholder="Search AAPL or Apple Inc."
                autoComplete="off"
                aria-controls="watchlist-search-results"
                aria-expanded={Boolean(normalizedQuery && searchResults.length)}
              />
            </div>
          </label>
          <button
            className="watchlist-add-button"
            type="submit"
            disabled={!normalizedQuery || isDuplicate || isAdding || !watchlist}
          >
            {addButtonLabel}
          </button>
        </form>

        {normalizedQuery && (
          <div className="watchlist-search-results" id="watchlist-search-results">
            {searchResults.length ? (
              <ul aria-label="Matching securities">
                {searchResults.map((security) => {
                  const isTracked = trackedSecurityIds.has(security.id)
                  return (
                    <li key={security.id}>
                      <button type="button" onClick={() => updateQuery(security.symbol)}>
                        <strong>{security.symbol}</strong>
                        <span>{security.company}</span>
                        {isTracked && <small>Already tracked</small>}
                      </button>
                    </li>
                  )
                })}
              </ul>
            ) : (
              <p>No securities match "{query.trim()}".</p>
            )}
          </div>
        )}

        <p
          className={`watchlist-feedback${notice ? ` is-${notice.tone}` : ''}`}
          aria-live="polite"
        >
          {notice?.message ?? 'Available securities are loaded from the Django API.'}
        </p>
      </section>

      <section className="watchlist-summary-grid" aria-label="Watchlist summary">
        <article className="watchlist-summary-card">
          <span>Total Stocks</span>
          <strong>{totalStocks}</strong>
          <small>Currently tracked</small>
        </article>
        <article className="watchlist-summary-card is-gainer">
          <span>Gainers</span>
          <strong>{gainers}</strong>
          <small>Positive daily change</small>
        </article>
        <article className="watchlist-summary-card is-decliner">
          <span>Decliners</span>
          <strong>{decliners}</strong>
          <small>Negative daily change</small>
        </article>
      </section>

      <section className="watchlist-list-card" aria-labelledby="tracked-stocks-title">
        <div className="watchlist-list-heading">
          <div>
            <p>Saved symbols</p>
            <h2 id="tracked-stocks-title">Tracked Stocks</h2>
          </div>
          <span>{totalStocks} {totalStocks === 1 ? 'stock' : 'stocks'}</span>
        </div>

        {selectedStocks.length ? (
          <div className="watchlist-page-table-wrap">
            <table className="watchlist-page-table">
              <caption className="sr-only">Current watchlist market and technical status</caption>
              <thead>
                <tr>
                  <th scope="col">Symbol</th>
                  <th scope="col">Company</th>
                  <th scope="col">Price</th>
                  <th scope="col">Daily Change</th>
                  <th scope="col">Change %</th>
                  <th scope="col">Mini Trend</th>
                  <th scope="col">RSI Status</th>
                  <th scope="col">MACD Status</th>
                  <th scope="col">Overall Trend</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {selectedStocks.map((stock) => {
                  const isRemoving = removingItemId === stock.itemId
                  return (
                    <tr key={stock.itemId}>
                      <td data-label="Symbol"><strong className="watchlist-page-symbol">{stock.symbol}</strong></td>
                      <td data-label="Company"><span className="watchlist-page-company">{stock.company}</span></td>
                      <td data-label="Price"><strong className="watchlist-page-price">{formatCurrency(stock.price)}</strong></td>
                      <td data-label="Daily Change">
                        <span className={`watchlist-page-move is-${stock.direction}`}>
                          {formatSignedCurrency(stock.dailyChange)}
                        </span>
                      </td>
                      <td data-label="Change %">
                        <span className={`watchlist-page-move is-${stock.direction}`}>
                          {formatSignedPercent(stock.changePercent)}
                        </span>
                      </td>
                      <td data-label="Mini Trend">
                        <span className={`watchlist-mini-trend is-${stock.direction}`}>
                          <span aria-hidden="true">
                            {stock.direction === 'up' ? '+' : stock.direction === 'down' ? '-' : '0'}
                          </span>
                          <Sparkline
                            values={stock.trend}
                            color={stock.direction === 'up' ? '#2bbf8a' : stock.direction === 'down' ? '#ef6a78' : '#9aa3b2'}
                            width={82}
                            height={28}
                          />
                          <span className="sr-only">
                            {stock.direction === 'up' ? 'Upward' : stock.direction === 'down' ? 'Downward' : 'Flat'} mini trend
                          </span>
                        </span>
                      </td>
                      <td data-label="RSI Status">
                        <span className={`watchlist-status ${getStatusTone(stock.rsiStatus)}`}>
                          {stock.rsiStatus}
                        </span>
                      </td>
                      <td data-label="MACD Status">
                        <span className={`watchlist-status ${getStatusTone(stock.macdStatus)}`}>
                          {stock.macdStatus}
                        </span>
                      </td>
                      <td data-label="Overall Trend">
                        <span className={`watchlist-status ${getStatusTone(stock.overallTrend)}`}>
                          {stock.overallTrend}
                        </span>
                      </td>
                      <td data-label="Actions">
                        <div className="watchlist-row-actions">
                          <button
                            type="button"
                            onClick={() => onViewAnalysis(stock.symbol)}
                            aria-label={`View ${stock.symbol} analysis`}
                          >
                            View Analysis
                          </button>
                          <button
                            className="is-remove"
                            type="button"
                            onClick={() => handleRemove(stock)}
                            disabled={isRemoving}
                            aria-label={`Remove ${stock.symbol} from watchlist`}
                          >
                            {isRemoving ? 'Removing...' : 'Remove'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="watchlist-empty-state">
            <span className="watchlist-empty-icon" aria-hidden="true"><Icon name="watchlist" /></span>
            <h3>Your watchlist is empty.</h3>
            <p>Search for a security and add it to start tracking market activity.</p>
            <button type="button" onClick={focusSearch}>Add Stock</button>
          </div>
        )}
      </section>
    </main>
  )
}
