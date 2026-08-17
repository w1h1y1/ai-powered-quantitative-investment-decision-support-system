import { useEffect, useId, useRef, useState } from 'react'
import { securityApi } from '../../services/securityApi'
import {
  filterLocalSecurityOptions,
  getSecuritySearchKey,
  mergeSecuritySearchOptions,
  securitySearchDebounceMs,
  securitySearchMinimumCharacters,
} from './securitySearchModel'

export default function SecuritySearchSelect({
  id,
  localSecurities,
  selectedSecurity,
  disabled = false,
  invalid = false,
  describedBy,
  clearSelectionOnEdit = true,
  onSelect,
}) {
  const generatedId = useId()
  const listboxId = `${id || generatedId}-results`
  const rootRef = useRef(null)
  const requestIdRef = useRef(0)
  const [query, setQuery] = useState(selectedSecurity?.symbol ?? '')
  const [isOpen, setIsOpen] = useState(false)
  const [hasEdited, setHasEdited] = useState(false)
  const [results, setResults] = useState(() => filterLocalSecurityOptions(localSecurities))
  const [activeIndex, setActiveIndex] = useState(0)
  const [isSearching, setIsSearching] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [hasSearched, setHasSearched] = useState(false)

  useEffect(() => {
    if (selectedSecurity?.symbol) setQuery(selectedSecurity.symbol)
  }, [selectedSecurity?.symbol])

  useEffect(() => {
    const closeOnOutsidePointer = (event) => {
      if (!rootRef.current?.contains(event.target)) setIsOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer)
    return () => document.removeEventListener('pointerdown', closeOnOutsidePointer)
  }, [])

  useEffect(() => {
    if (!isOpen || !hasEdited) return undefined

    const normalizedQuery = query.trim()
    const requestId = requestIdRef.current + 1
    requestIdRef.current = requestId
    setActiveIndex(0)
    setSearchError('')

    if (normalizedQuery.length < securitySearchMinimumCharacters) {
      setResults(filterLocalSecurityOptions(localSecurities, normalizedQuery))
      setIsSearching(false)
      setHasSearched(false)
      return undefined
    }

    setResults(filterLocalSecurityOptions(localSecurities, normalizedQuery))
    setIsSearching(true)
    setHasSearched(false)
    const timer = window.setTimeout(async () => {
      try {
        const payload = await securityApi.search(normalizedQuery)
        if (requestIdRef.current !== requestId) return
        setResults(mergeSecuritySearchOptions(localSecurities, payload?.items, normalizedQuery))
        setSearchError(payload?.metadata?.remote_error || '')
        setHasSearched(true)
      } catch (error) {
        if (requestIdRef.current !== requestId) return
        setResults(filterLocalSecurityOptions(localSecurities, normalizedQuery))
        setSearchError(error?.message || 'Remote security search is temporarily unavailable.')
        setHasSearched(true)
      } finally {
        if (requestIdRef.current === requestId) setIsSearching(false)
      }
    }, securitySearchDebounceMs)

    return () => window.clearTimeout(timer)
  }, [hasEdited, isOpen, localSecurities, query])

  const openLocalResults = () => {
    if (disabled) return
    setIsOpen(true)
    setHasEdited(false)
    setResults(filterLocalSecurityOptions(localSecurities))
    setActiveIndex(0)
    setSearchError('')
    setHasSearched(false)
  }

  const updateQuery = (event) => {
    const nextQuery = event.target.value
    setQuery(nextQuery)
    setResults(filterLocalSecurityOptions(localSecurities, nextQuery.trim()))
    setIsOpen(true)
    setHasEdited(true)
    if (
      clearSelectionOnEdit
      && selectedSecurity
      && nextQuery.trim().toUpperCase() !== selectedSecurity.symbol
    ) onSelect(null)
  }

  const selectResult = (security) => {
    setQuery(security.symbol)
    setIsOpen(false)
    setHasEdited(false)
    setSearchError('')
    onSelect({ ...security, search_query: security.search_query || query.trim() })
  }

  const handleKeyDown = (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setIsOpen(true)
      setActiveIndex((current) => Math.min(current + 1, Math.max(results.length - 1, 0)))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex((current) => Math.max(current - 1, 0))
    } else if (event.key === 'Enter' && isOpen && results[activeIndex]) {
      event.preventDefault()
      selectResult(results[activeIndex])
    } else if (event.key === 'Escape') {
      setIsOpen(false)
      if (selectedSecurity) setQuery(selectedSecurity.symbol)
    }
  }

  const activeOption = results[activeIndex]
  const activeOptionId = activeOption ? `${listboxId}-${activeIndex}` : undefined

  return (
    <div className="security-search-select" ref={rootRef}>
      <input
        id={id}
        type="search"
        role="combobox"
        value={query}
        placeholder="Search AAPL or Apple Inc."
        autoComplete="off"
        disabled={disabled}
        aria-invalid={invalid}
        aria-describedby={describedBy}
        aria-autocomplete="list"
        aria-controls={listboxId}
        aria-expanded={isOpen}
        aria-activedescendant={isOpen ? activeOptionId : undefined}
        onFocus={openLocalResults}
        onChange={updateQuery}
        onKeyDown={handleKeyDown}
      />

      {isOpen && (
        <div className="security-search-popover">
          {results.length ? (
            <ul id={listboxId} role="listbox" aria-label="Asset search results">
              {results.map((security, index) => {
                const optionKey = getSecuritySearchKey(security)
                const isSelected = optionKey === getSecuritySearchKey(selectedSecurity)
                return (
                  <li
                    id={`${listboxId}-${index}`}
                    role="option"
                    aria-selected={isSelected}
                    key={`${optionKey}-${index}`}
                  >
                    <button
                      type="button"
                      className={index === activeIndex ? 'is-active' : ''}
                      onMouseEnter={() => setActiveIndex(index)}
                      onClick={() => selectResult(security)}
                    >
                      <span>
                        <strong>{security.symbol}</strong>
                        <small>{security.name}</small>
                      </span>
                      <span className="security-search-meta">
                        <small>{[security.exchange, security.instrument_type].filter(Boolean).join(' · ')}</small>
                        <b className={security.is_local ? 'is-local' : 'is-remote'}>
                          {security.is_local ? 'Local' : 'Remote'}
                        </b>
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          ) : isSearching ? (
            <p className="security-search-state">Searching...</p>
          ) : hasSearched ? (
            <p className="security-search-state">No securities found.</p>
          ) : (
            <p className="security-search-state">Type at least 2 characters to search remote securities.</p>
          )}
          {isSearching && results.length ? <p className="security-search-state">Searching remote securities...</p> : null}
          {searchError ? <p className="security-search-warning">{searchError}</p> : null}
        </div>
      )}
    </div>
  )
}
