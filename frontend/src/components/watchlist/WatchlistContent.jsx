import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../Icon'
import Sparkline from '../dashboard/Sparkline'
import { securityApi } from '../../services/securityApi'
import { watchlistApi } from '../../services/watchlistApi'
import {
  formatWatchlistCurrency,
  formatWatchlistSignedCurrency,
  formatWatchlistSignedPercent,
  getWatchlistErrorMessage,
  getWatchlistStatusTone,
  buildWatchlistStock,
  loadUserWatchlistData,
  notifyWatchlistChanged,
} from '../../services/watchlistDataService'

function getSearchSecurityKey(security) {
  const symbol = String(security?.symbol ?? '').trim().toUpperCase()
  if (!symbol) return ''

  const micCode = String(security?.mic_code ?? security?.micCode ?? '').trim().toUpperCase()
  if (micCode) return `${symbol}:${micCode}`

  const exchange = String(security?.exchange ?? '').trim().toLowerCase()
  return exchange ? `${symbol}:${exchange}` : symbol
}

function normalizeSearchResult(result, searchQuery) {
  if (!result) return null
  return {
    id: result.id ?? null,
    symbol: String(result.symbol ?? '').trim().toUpperCase(),
    name: String(result.name ?? '').trim(),
    exchange: String(result.exchange ?? '').trim(),
    mic_code: String(result.mic_code ?? '').trim().toUpperCase(),
    instrument_type: String(result.instrument_type ?? '').trim(),
    country: String(result.country ?? '').trim(),
    currency: String(result.currency ?? 'USD').trim().toUpperCase(),
    is_local: result.is_local === true,
    is_preferred: result.is_preferred === true,
    search_query: searchQuery,
  }
}

function upsertWatchlistItem(items, nextItem) {
  if (!nextItem?.id) return items
  const existingIndex = items.findIndex((item) => item.id === nextItem.id)
  if (existingIndex === -1) return [nextItem, ...items]

  return items.map((item, index) => (index === existingIndex ? nextItem : item))
}

function upsertWatchlistStock(stocks, nextItem) {
  const nextStock = buildWatchlistStock(nextItem?.security, nextItem?.id)
  if (!nextStock) return stocks

  const existingIndex = stocks.findIndex((stock) => stock.itemId === nextStock.itemId)
  if (existingIndex === -1) return [nextStock, ...stocks]

  return stocks.map((stock, index) => (index === existingIndex ? nextStock : stock))
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

export default function WatchlistContent({ onViewAnalysis }) {
  const [watchlist, setWatchlist] = useState(null)
  const [watchlistItems, setWatchlistItems] = useState([])
  const [initialLoading, setInitialLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [selectedSearchResult, setSelectedSearchResult] = useState(null)
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [hasSearched, setHasSearched] = useState(false)
  const [feedback, setFeedback] = useState(null)
  const [addingSecurity, setAddingSecurity] = useState(false)
  const [summaryRefreshing, setSummaryRefreshing] = useState(false)
  const [quoteError, setQuoteError] = useState('')
  const [selectedStocks, setSelectedStocks] = useState([])
  const [deletingSecurityId, setDeletingSecurityId] = useState(null)
  const searchInputRef = useRef(null)
  const searchRequestIdRef = useRef(0)
  const watchlistLoadRequestIdRef = useRef(0)

  const restoreScrollPosition = useCallback((scrollY) => {
    if (typeof window === 'undefined' || scrollY === null) return
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: scrollY, left: window.scrollX, behavior: 'auto' })
    })
  }, [])

  const applyWatchlistData = useCallback((data) => {
    setWatchlist(data.watchlist)
    setWatchlistItems(data.watchlistItems)
    setSelectedStocks(data.selectedStocks)
    setQuoteError(data.quoteError)
  }, [])

  const refreshWatchlistData = useCallback(async ({ force = false, initial = false, preserveScrollY = null } = {}) => {
    const requestId = watchlistLoadRequestIdRef.current + 1
    watchlistLoadRequestIdRef.current = requestId

    if (initial) {
      setInitialLoading(true)
      setLoadError('')
      setFeedback(null)
      setWatchlist(null)
      setWatchlistItems([])
      setQuoteError('')
      setSelectedStocks([])
    } else {
      setSummaryRefreshing(true)
    }

    try {
      const data = await loadUserWatchlistData({ force })
      if (watchlistLoadRequestIdRef.current !== requestId) return
      applyWatchlistData(data)
      if (preserveScrollY !== null) restoreScrollPosition(preserveScrollY)
    } catch (error) {
      if (watchlistLoadRequestIdRef.current !== requestId) return
      if (initial) {
        setLoadError(error.message || 'Request failed. Please try again.')
      } else {
        setQuoteError(getWatchlistErrorMessage(error))
      }
    } finally {
      if (watchlistLoadRequestIdRef.current !== requestId) return
      if (initial) {
        setInitialLoading(false)
      } else {
        setSummaryRefreshing(false)
      }
    }
  }, [applyWatchlistData, restoreScrollPosition])

  useEffect(() => {
    refreshWatchlistData({ initial: true })
  }, [refreshWatchlistData])

  const trackedSecurityIds = useMemo(
    () => new Set(watchlistItems.map((item) => item.security?.id).filter(Boolean)),
    [watchlistItems],
  )
  const trackedSecurityKeys = useMemo(
    () => new Set(
      watchlistItems
        .map((item) => getSearchSecurityKey(item.security))
        .filter(Boolean),
    ),
    [watchlistItems],
  )
  const normalizedQuery = query.trim()
  const canSearch = normalizedQuery.length >= 2
  const selectedSearchKey = getSearchSecurityKey(selectedSearchResult)
  const isDuplicate = Boolean(
    selectedSearchResult
    && (
      (selectedSearchResult.id && trackedSecurityIds.has(selectedSearchResult.id))
      || (selectedSearchKey && trackedSecurityKeys.has(selectedSearchKey))
    ),
  )
  const totalStocks = selectedStocks.length
  const gainers = selectedStocks.filter((stock) => stock.dailyChange > 0).length
  const decliners = selectedStocks.filter((stock) => stock.dailyChange < 0).length

  useEffect(() => {
    if (!canSearch) {
      setSearchResults([])
      setSearchLoading(false)
      setSearchError('')
      setHasSearched(false)
      return undefined
    }

    if (selectedSearchResult && normalizedQuery.toUpperCase() === selectedSearchResult.symbol) {
      setSearchResults([selectedSearchResult])
      setSearchLoading(false)
      setSearchError('')
      setHasSearched(true)
      return undefined
    }

    const requestId = searchRequestIdRef.current + 1
    searchRequestIdRef.current = requestId
    setSearchLoading(true)
    setSearchError('')
    setHasSearched(false)

    const timer = window.setTimeout(async () => {
      try {
        const payload = await securityApi.search(normalizedQuery)
        if (searchRequestIdRef.current !== requestId) return

        const items = Array.isArray(payload?.items) ? payload.items : []
        setSearchResults(items.map((item) => normalizeSearchResult(item, normalizedQuery)).filter(Boolean))
        setSearchError(payload?.metadata?.remote_error || '')
        setHasSearched(true)
      } catch (error) {
        if (searchRequestIdRef.current !== requestId) return
        setSearchResults([])
        setSearchError(getWatchlistErrorMessage(error))
        setHasSearched(true)
      } finally {
        if (searchRequestIdRef.current === requestId) setSearchLoading(false)
      }
    }, 450)

    return () => {
      window.clearTimeout(timer)
    }
  }, [canSearch, normalizedQuery, selectedSearchResult])

  const updateQuery = (value) => {
    setQuery(value)
    setFeedback(null)
    setSearchError('')
    if (selectedSearchResult && value.trim().toUpperCase() !== selectedSearchResult.symbol) {
      setSelectedSearchResult(null)
    }
  }

  const selectSearchResult = (result) => {
    setSelectedSearchResult(result)
    setQuery(result.symbol)
    setFeedback(null)
    setSearchError('')
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

    if (!selectedSearchResult) {
      setFeedback({
        tone: 'error',
        message: searchResults.length
          ? 'Select one security from the matching results.'
          : 'Search for a symbol or company and select a result.',
      })
      return
    }

    if (isDuplicate) {
      setFeedback({
        tone: 'error',
        message: `${selectedSearchResult.symbol} is already in your watchlist.`,
      })
      return
    }

    const scrollY = typeof window === 'undefined' ? null : window.scrollY
    setAddingSecurity(true)
    try {
      const response = await watchlistApi.addSymbol({
        id: selectedSearchResult.id,
        symbol: selectedSearchResult.symbol,
        name: selectedSearchResult.name,
        exchange: selectedSearchResult.exchange,
        mic_code: selectedSearchResult.mic_code,
        instrument_type: selectedSearchResult.instrument_type,
        country: selectedSearchResult.country,
        currency: selectedSearchResult.currency,
        search_query: selectedSearchResult.search_query || query.trim(),
      })
      const addedSymbol = response?.security?.symbol || selectedSearchResult.symbol
      const addedItem = response?.watchlist_item
      if (addedItem?.id) {
        setWatchlistItems((current) => upsertWatchlistItem(current, addedItem))
        setSelectedStocks((current) => upsertWatchlistStock(current, addedItem))
      }
      notifyWatchlistChanged()
      setQuery('')
      setSearchResults([])
      setSelectedSearchResult(null)
      setHasSearched(false)
      setSearchError('')
      setFeedback({
        tone: 'success',
        message: response?.status === 'already_tracked'
          ? `${addedSymbol} is already in your watchlist.`
          : `${addedSymbol} was added to your watchlist.`,
      })
      searchInputRef.current?.focus()
      restoreScrollPosition(scrollY)
      refreshWatchlistData({ force: true, preserveScrollY: scrollY })
    } catch (error) {
      setFeedback({
        tone: 'error',
        message: getWatchlistErrorMessage(error),
      })
    } finally {
      setAddingSecurity(false)
    }
  }

  const handleRemove = async (stock) => {
    const shouldRemove = window.confirm(`Remove ${stock.symbol} - ${stock.company} from your watchlist?`)
    if (!shouldRemove) return

    const scrollY = typeof window === 'undefined' ? null : window.scrollY
    setDeletingSecurityId(stock.itemId)
    setFeedback(null)
    try {
      await watchlistApi.removeItem(stock.itemId)
      setWatchlistItems((current) => current.filter((item) => item.id !== stock.itemId))
      setSelectedStocks((current) => current.filter((item) => item.itemId !== stock.itemId))
      notifyWatchlistChanged()
      restoreScrollPosition(scrollY)
      refreshWatchlistData({ force: true, preserveScrollY: scrollY })
      setFeedback({
        tone: 'success',
        message: `${stock.symbol} was removed from your watchlist.`,
      })
    } catch (error) {
      setFeedback({
        tone: 'error',
        message: getWatchlistErrorMessage(error),
      })
    } finally {
      setDeletingSecurityId(null)
    }
  }

  const focusSearch = () => {
    searchInputRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    window.setTimeout(() => {
      searchInputRef.current?.focus()
    }, 0)
  }

  const notice = isDuplicate
    ? { tone: 'error', message: `${selectedSearchResult.symbol} is already in your watchlist.` }
    : feedback
  const addButtonLabel = addingSecurity ? 'Adding...' : 'Add to Watchlist'

  if (initialLoading) {
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
        <WatchlistStateCard actionLabel="Retry" onAction={() => refreshWatchlistData({ initial: true })} tone="is-error">
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
          <span>Track selected securities saved to your Django Watchlist.</span>
        </div>
        <div className="demo-data-status" aria-label="Watchlist data source">
          <strong>Watchlist API</strong>
          <span>
            {quoteError
              ? quoteError
              : summaryRefreshing
                ? 'Refreshing latest Watchlist data...'
                : selectedStocks.some((stock) => stock.price !== null)
                ? 'Quotes from market-data API with cache fallback'
                : 'Security records from PostgreSQL'}
          </span>
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
                aria-expanded={Boolean(canSearch && searchResults.length)}
              />
            </div>
          </label>
          <button
            className="watchlist-add-button"
            type="submit"
            disabled={!selectedSearchResult || isDuplicate || addingSecurity || !watchlist}
          >
            {addButtonLabel}
          </button>
        </form>

        {canSearch && (
          <div className="watchlist-search-results" id="watchlist-search-results">
            {searchLoading ? (
              <p>Searching securities...</p>
            ) : searchError && !searchResults.length ? (
              <p>{searchError}</p>
            ) : searchResults.length ? (
              <ul aria-label="Matching securities">
                {searchResults.map((security, index) => {
                  const resultKey = getSearchSecurityKey(security)
                  const isSelected = selectedSearchKey && resultKey === selectedSearchKey
                  const isTracked = Boolean(
                    (security.id && trackedSecurityIds.has(security.id))
                    || (resultKey && trackedSecurityKeys.has(resultKey)),
                  )
                  return (
                    <li key={`${resultKey || security.symbol}-${index}`}>
                      <button
                        type="button"
                        className={isSelected ? 'is-selected' : ''}
                        onClick={() => selectSearchResult(security)}
                        aria-pressed={isSelected}
                      >
                        <strong>{security.symbol}</strong>
                        <span>{security.name}</span>
                        <small>{[security.exchange, security.instrument_type].filter(Boolean).join(' - ')}</small>
                        <small>{security.is_local ? 'Local' : 'Remote'}{isTracked ? ' - Already tracked' : ''}</small>
                      </button>
                    </li>
                  )
                })}
              </ul>
            ) : hasSearched ? (
              <p>No securities match "{query.trim()}".</p>
            ) : (
              <p>Type at least 2 characters to search symbols and company names.</p>
            )}
            {searchError && searchResults.length ? <p>{searchError}</p> : null}
          </div>
        )}

        <p
          className={`watchlist-feedback${notice ? ` is-${notice.tone}` : ''}`}
          aria-live="polite"
        >
          {notice?.message ?? 'Search results include local securities and verified Twelve Data symbols.'}
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
              <caption className="sr-only">Current saved Watchlist securities</caption>
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
                  const isRemoving = deletingSecurityId === stock.itemId
                  return (
                    <tr key={stock.itemId}>
                      <td data-label="Symbol"><strong className="watchlist-page-symbol">{stock.symbol}</strong></td>
                      <td data-label="Company"><span className="watchlist-page-company">{stock.company}</span></td>
                      <td data-label="Price">
                        <strong
                          className="watchlist-page-price"
                          title={stock.latestAsOf ? `Latest available: ${stock.latestAsOf}` : undefined}
                        >
                          {formatWatchlistCurrency(stock.price, stock.currency)}
                        </strong>
                      </td>
                      <td data-label="Daily Change">
                        <span className={`watchlist-page-move is-${stock.direction}`}>
                          {formatWatchlistSignedCurrency(stock.dailyChange, stock.currency)}
                        </span>
                      </td>
                      <td data-label="Change %">
                        <span className={`watchlist-page-move is-${stock.direction}`}>
                          {formatWatchlistSignedPercent(stock.changePercent)}
                        </span>
                      </td>
                      <td data-label="Mini Trend">
                        <span className={`watchlist-mini-trend is-${stock.direction}`}>
                          {stock.trend.length >= 2 ? (
                            <>
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
                            </>
                          ) : (
                            <span className="watchlist-mini-trend-unavailable">—</span>
                          )}
                        </span>
                      </td>
                      <td data-label="RSI Status">
                        <span className={`watchlist-status ${getWatchlistStatusTone(stock.rsiStatus)}`}>
                          {stock.rsiStatus}
                        </span>
                      </td>
                      <td data-label="MACD Status">
                        <span className={`watchlist-status ${getWatchlistStatusTone(stock.macdStatus)}`}>
                          {stock.macdStatus}
                        </span>
                      </td>
                      <td data-label="Overall Trend">
                        <span className={`watchlist-status ${getWatchlistStatusTone(stock.overallTrend)}`}>
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
