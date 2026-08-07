import { useEffect, useMemo, useRef, useState } from 'react'
import { securityApi } from '../../services/securityApi'
import { formatQuantity } from './portfolioMath'
import { buildTradeEstimate, validateTradeFields } from './tradeWorkflow'

function toDateTimeLocalValue(date = new Date()) {
  const timezoneOffset = date.getTimezoneOffset() * 60000
  return new Date(date.getTime() - timezoneOffset).toISOString().slice(0, 16)
}

function normalizeSearchResult(result, searchQuery) {
  if (!result) return null
  return {
    id: result.id ?? null,
    symbol: String(result.symbol ?? '').trim().toUpperCase(),
    name: String(result.name ?? '').trim(),
    exchange: String(result.exchange ?? '').trim(),
    mic_code: String(result.mic_code ?? '').trim().toUpperCase(),
    instrument_type: String(result.instrument_type ?? result.type ?? '').trim(),
    country: String(result.country ?? '').trim(),
    currency: String(result.currency ?? 'USD').trim().toUpperCase(),
    is_local: result.is_local === true || Boolean(result.id),
    is_preferred: result.is_preferred === true,
    search_query: searchQuery,
  }
}

function normalizeLocalSecurityResult(security) {
  if (!security) return null
  return normalizeSearchResult({
    id: security.id,
    symbol: security.symbol,
    name: security.name,
    exchange: security.exchange,
    mic_code: security.mic_code,
    instrument_type: security.instrument_type || security.type,
    country: security.country,
    currency: security.currency,
    is_local: true,
  }, security.symbol)
}

function getSearchErrorMessage(error) {
  if (error?.status === 429) return 'Market data provider rate limit reached. Please try again later.'
  return error?.message || 'Security search failed. Please try again.'
}

export default function TradeDialog({
  holding = null,
  holdings = [],
  isSubmitting,
  onClose,
  onSave,
  portfolio,
  securities = [],
  transactionType = 'BUY',
}) {
  const isSellMode = transactionType === 'SELL'
  const sellableHoldings = useMemo(
    () => holdings.filter((item) => Number(item.quantity) > 0),
    [holdings],
  )
  const initialBuySecurity = !isSellMode && securities[0] ? normalizeLocalSecurityResult(securities[0]) : null
  const initialSellSecurityId = isSellMode
    ? String(holding?.securityId ?? sellableHoldings[0]?.securityId ?? '')
    : ''
  const [selectedSecurityId, setSelectedSecurityId] = useState(initialSellSecurityId)
  const [securityQuery, setSecurityQuery] = useState(initialBuySecurity?.symbol ?? '')
  const [selectedSearchResult, setSelectedSearchResult] = useState(initialBuySecurity)
  const [securitySearchResults, setSecuritySearchResults] = useState(initialBuySecurity ? [initialBuySecurity] : [])
  const [securitySearchLoading, setSecuritySearchLoading] = useState(false)
  const [securitySearchError, setSecuritySearchError] = useState('')
  const [hasSearchedSecurity, setHasSearchedSecurity] = useState(false)
  const [quantity, setQuantity] = useState('')
  const [price, setPrice] = useState('')
  const [transactionDate, setTransactionDate] = useState(toDateTimeLocalValue())
  const [fee, setFee] = useState('0')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
  const searchRequestIdRef = useRef(0)
  const securitySelectRef = useRef(null)
  const quantityInputRef = useRef(null)
  const priceInputRef = useRef(null)
  const transactionDateInputRef = useRef(null)
  const feeInputRef = useRef(null)
  const dialogRef = useRef(null)
  const submitLockRef = useRef(false)

  const selectedHolding = useMemo(
    () => holdings.find((item) => String(item.securityId) === selectedSecurityId) ?? holding,
    [holding, holdings, selectedSecurityId],
  )
  const selectedSecurity = isSellMode
    ? (selectedHolding ? {
      id: selectedHolding.securityId,
      symbol: selectedHolding.symbol,
      name: selectedHolding.asset,
      type: selectedHolding.type,
    } : null)
    : selectedSearchResult ? {
      id: selectedSearchResult.id,
      symbol: selectedSearchResult.symbol,
      name: selectedSearchResult.name,
      type: selectedSearchResult.instrument_type || 'Security',
      exchange: selectedSearchResult.exchange,
    } : null
  const availableQuantity = selectedHolding?.quantity ?? 0
  const dialogTitle = isSellMode ? 'Sell Security' : 'Buy Security'
  const estimateLabel = isSellMode ? 'Estimated proceeds' : 'Estimated total'
  const fieldRefs = {
    fee: feeInputRef,
    price: priceInputRef,
    quantity: quantityInputRef,
    security: securitySelectRef,
    transactionDate: transactionDateInputRef,
  }

  const getTradeValues = (overrides = {}) => ({
    availableQuantity: isSellMode ? availableQuantity : undefined,
    portfolioId: portfolio?.id,
    securityId: selectedSecurity?.id || undefined,
    securitySubmission: !isSellMode && !selectedSearchResult?.id ? selectedSearchResult : undefined,
    transactionType,
    quantity,
    price,
    transactionDate,
    fee,
    notes,
    ...overrides,
  })

  const focusField = (fieldName) => {
    fieldRefs[fieldName]?.current?.focus()
  }

  const updateFieldError = (fieldName, nextValues) => {
    const nextFieldErrors = validateTradeFields(nextValues).fieldErrors
    const fieldsToUpdate = new Set([fieldName])
    if (['fee', 'price', 'quantity'].includes(fieldName)) fieldsToUpdate.add('fee')

    setFieldErrors((previousErrors) => {
      const updatedErrors = { ...previousErrors }
      fieldsToUpdate.forEach((field) => {
        if (nextFieldErrors[field]) {
          updatedErrors[field] = nextFieldErrors[field]
        } else {
          delete updatedErrors[field]
        }
      })
      return updatedErrors
    })
    setError('')
  }

  const updateSecurityQuery = (value) => {
    setSecurityQuery(value)
    setSecuritySearchError('')
    setError('')
    if (selectedSearchResult && value.trim().toUpperCase() !== selectedSearchResult.symbol) {
      setSelectedSearchResult(null)
      setSelectedSecurityId('')
    }
    updateFieldError('security', {
      ...getTradeValues(),
      securityId: undefined,
      securitySubmission: undefined,
    })
  }

  const selectSearchResult = (result) => {
    setSelectedSearchResult(result)
    setSelectedSecurityId(result.id ? String(result.id) : '')
    setSecurityQuery(result.symbol)
    setSecuritySearchError('')
    setError('')
    updateFieldError('security', {
      ...getTradeValues(),
      securityId: result.id || undefined,
      securitySubmission: result.id ? undefined : result,
    })
    quantityInputRef.current?.focus()
  }

  const tradeValues = getTradeValues()
  const tradeEstimate = buildTradeEstimate(tradeValues)
  const normalizedSecurityQuery = securityQuery.trim()
  const canSearchSecurity = !isSellMode && normalizedSecurityQuery.length >= 2

  useEffect(() => {
    if (isSellMode) return undefined

    if (!canSearchSecurity) {
      setSecuritySearchResults([])
      setSecuritySearchLoading(false)
      setSecuritySearchError('')
      setHasSearchedSecurity(false)
      return undefined
    }

    if (selectedSearchResult && normalizedSecurityQuery.toUpperCase() === selectedSearchResult.symbol) {
      setSecuritySearchResults([selectedSearchResult])
      setSecuritySearchLoading(false)
      setSecuritySearchError('')
      setHasSearchedSecurity(true)
      return undefined
    }

    const requestId = searchRequestIdRef.current + 1
    searchRequestIdRef.current = requestId
    setSecuritySearchLoading(true)
    setSecuritySearchError('')
    setHasSearchedSecurity(false)

    const timer = window.setTimeout(async () => {
      try {
        const payload = await securityApi.search(normalizedSecurityQuery)
        if (searchRequestIdRef.current !== requestId) return

        const items = Array.isArray(payload?.items) ? payload.items : []
        setSecuritySearchResults(items.map((item) => normalizeSearchResult(item, normalizedSecurityQuery)).filter(Boolean))
        setSecuritySearchError(payload?.metadata?.remote_error || '')
        setHasSearchedSecurity(true)
      } catch (searchError) {
        if (searchRequestIdRef.current !== requestId) return
        setSecuritySearchResults([])
        setSecuritySearchError(getSearchErrorMessage(searchError))
        setHasSearchedSecurity(true)
      } finally {
        if (searchRequestIdRef.current === requestId) setSecuritySearchLoading(false)
      }
    }, 450)

    return () => window.clearTimeout(timer)
  }, [canSearchSecurity, isSellMode, normalizedSecurityQuery, selectedSearchResult])

  useEffect(() => {
    const previouslyFocusedElement = document.activeElement
    const previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    if (isSellMode) {
      quantityInputRef.current?.focus()
    } else {
      securitySelectRef.current?.focus()
    }

    return () => {
      document.body.style.overflow = previousBodyOverflow
      previouslyFocusedElement?.focus()
    }
  }, [isSellMode])

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === 'Escape' && !isSubmitting) onClose()

      if (event.key === 'Tab') {
        const focusableElements = dialogRef.current?.querySelectorAll(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])',
        )
        if (!focusableElements?.length) return

        const firstElement = focusableElements[0]
        const lastElement = focusableElements[focusableElements.length - 1]
        if (event.shiftKey && document.activeElement === firstElement) {
          event.preventDefault()
          lastElement.focus()
        } else if (!event.shiftKey && document.activeElement === lastElement) {
          event.preventDefault()
          firstElement.focus()
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isSubmitting, onClose])

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (isSubmitting || submitLockRef.current) return

    const validation = validateTradeFields(getTradeValues())
    if (!validation.isValid) {
      setFieldErrors(validation.fieldErrors)
      setError(validation.formError)
      if (validation.firstField) focusField(validation.firstField)
      return
    }

    submitLockRef.current = true
    const saveError = await onSave(getTradeValues())

    if (saveError) {
      submitLockRef.current = false
      setError(saveError)
      return
    }

    onClose()
  }

  const clearError = () => setError('')

  return (
    <div className="portfolio-dialog-backdrop" role="presentation">
      <section
        ref={dialogRef}
        className="portfolio-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="trade-dialog-title"
      >
        <div className="portfolio-dialog-header">
          <div>
            <p>Portfolio transaction</p>
            <h2 id="trade-dialog-title">{dialogTitle}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close transaction form" disabled={isSubmitting}>X</button>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          <div className="portfolio-dialog-asset-summary" aria-label="Portfolio used for this transaction">
            <span>Portfolio</span>
            <div>
              <strong>{portfolio?.name || 'My Portfolio'}</strong>
              <small>Current authenticated user's Portfolio</small>
            </div>
            <b>{portfolio?.base_currency || 'USD'}</b>
          </div>

          {isSellMode ? (
            <label className="portfolio-dialog-single-field">
              <span>Security</span>
              <select
                ref={securitySelectRef}
                value={selectedSecurityId}
                onChange={(event) => {
                  setSelectedSecurityId(event.target.value)
                  updateFieldError('security', {
                    ...getTradeValues(),
                    securityId: Number(event.target.value),
                  })
                }}
                disabled={!sellableHoldings.length || isSubmitting}
                aria-invalid={fieldErrors.security ? 'true' : 'false'}
                aria-describedby={fieldErrors.security ? 'trade-security-error' : undefined}
              >
                {sellableHoldings.map((sellableHolding) => (
                  <option value={sellableHolding.securityId} key={sellableHolding.id ?? sellableHolding.securityId}>
                    {sellableHolding.symbol} - {sellableHolding.asset} - Available {formatQuantity(sellableHolding.quantity)}
                  </option>
                ))}
              </select>
              {fieldErrors.security && (
                <small className="portfolio-dialog-field-error" id="trade-security-error" role="alert">
                  {fieldErrors.security}
                </small>
              )}
            </label>
          ) : (
            <div className="portfolio-dialog-single-field">
              <label htmlFor="trade-security-search">
                <span>Security</span>
                <input
                  ref={securitySelectRef}
                  id="trade-security-search"
                  type="search"
                  autoComplete="off"
                  value={securityQuery}
                  onChange={(event) => updateSecurityQuery(event.target.value)}
                  placeholder="Search symbol or company"
                  disabled={isSubmitting}
                  role="combobox"
                  aria-autocomplete="list"
                  aria-controls="trade-security-search-results"
                  aria-expanded={Boolean(canSearchSecurity && securitySearchResults.length)}
                  aria-invalid={fieldErrors.security ? 'true' : 'false'}
                  aria-describedby={fieldErrors.security ? 'trade-security-error' : undefined}
                />
              </label>

              <div className="portfolio-security-search-results" id="trade-security-search-results">
                {securitySearchLoading ? (
                  <p>Searching securities...</p>
                ) : securitySearchError && !securitySearchResults.length ? (
                  <p>{securitySearchError}</p>
                ) : securitySearchResults.length ? (
                  <ul>
                    {securitySearchResults.map((result) => {
                      const isSelected = selectedSearchResult
                        && selectedSearchResult.symbol === result.symbol
                        && (selectedSearchResult.mic_code || selectedSearchResult.exchange)
                          === (result.mic_code || result.exchange)
                      return (
                        <li key={`${result.symbol}-${result.mic_code || result.exchange || 'remote'}`}>
                          <button
                            type="button"
                            className={isSelected ? 'is-selected' : ''}
                            onClick={() => selectSearchResult(result)}
                            disabled={isSubmitting}
                          >
                            <strong>{result.symbol}</strong>
                            <span>{result.name || result.symbol}</span>
                            <small>
                              {[result.exchange, result.instrument_type]
                                .filter(Boolean)
                                .join(' - ')}
                            </small>
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                ) : hasSearchedSecurity ? (
                  <p>No matching securities found.</p>
                ) : (
                  <p>Type at least 2 characters to search symbols and company names.</p>
                )}
                {securitySearchError && securitySearchResults.length ? <p>{securitySearchError}</p> : null}
              </div>

              {fieldErrors.security && (
                <small className="portfolio-dialog-field-error" id="trade-security-error" role="alert">
                  {fieldErrors.security}
                </small>
              )}
            </div>
          )}

          <div className="portfolio-dialog-form-grid is-numeric">
            <label>
              <span>Quantity</span>
              <input
                ref={quantityInputRef}
                type="text"
                inputMode="decimal"
                autoComplete="off"
                value={quantity}
                onChange={(event) => {
                  setQuantity(event.target.value)
                  updateFieldError('quantity', getTradeValues({ quantity: event.target.value }))
                }}
                placeholder="0.00"
                disabled={isSubmitting}
                aria-invalid={fieldErrors.quantity ? 'true' : 'false'}
                aria-describedby={fieldErrors.quantity ? 'trade-quantity-error' : undefined}
              />
              {fieldErrors.quantity && (
                <small className="portfolio-dialog-field-error" id="trade-quantity-error" role="alert">
                  {fieldErrors.quantity}
                </small>
              )}
            </label>
            <label>
              <span>Price</span>
              <input
                ref={priceInputRef}
                type="text"
                inputMode="decimal"
                autoComplete="off"
                value={price}
                onChange={(event) => {
                  setPrice(event.target.value)
                  updateFieldError('price', getTradeValues({ price: event.target.value }))
                }}
                placeholder="0.00"
                disabled={isSubmitting}
                aria-invalid={fieldErrors.price ? 'true' : 'false'}
                aria-describedby={fieldErrors.price ? 'trade-price-error' : undefined}
              />
              {fieldErrors.price && (
                <small className="portfolio-dialog-field-error" id="trade-price-error" role="alert">
                  {fieldErrors.price}
                </small>
              )}
            </label>
          </div>

          <div className="portfolio-dialog-form-grid is-numeric">
            <label>
              <span>Transaction Date</span>
              <input
                ref={transactionDateInputRef}
                type="datetime-local"
                value={transactionDate}
                onChange={(event) => {
                  setTransactionDate(event.target.value)
                  updateFieldError('transactionDate', getTradeValues({ transactionDate: event.target.value }))
                }}
                disabled={isSubmitting}
                aria-invalid={fieldErrors.transactionDate ? 'true' : 'false'}
                aria-describedby={fieldErrors.transactionDate ? 'trade-transaction-date-error' : undefined}
              />
              {fieldErrors.transactionDate && (
                <small className="portfolio-dialog-field-error" id="trade-transaction-date-error" role="alert">
                  {fieldErrors.transactionDate}
                </small>
              )}
            </label>
            <label>
              <span>Fee</span>
              <input
                ref={feeInputRef}
                type="text"
                inputMode="decimal"
                autoComplete="off"
                value={fee}
                onChange={(event) => {
                  setFee(event.target.value)
                  updateFieldError('fee', getTradeValues({ fee: event.target.value }))
                }}
                placeholder="0.00"
                disabled={isSubmitting}
                aria-invalid={fieldErrors.fee ? 'true' : 'false'}
                aria-describedby={fieldErrors.fee ? 'trade-fee-error' : undefined}
              />
              {fieldErrors.fee && (
                <small className="portfolio-dialog-field-error" id="trade-fee-error" role="alert">
                  {fieldErrors.fee}
                </small>
              )}
            </label>
          </div>

          <div className="portfolio-dialog-estimate" aria-live="polite">
            <span>{estimateLabel}</span>
            <strong>{tradeEstimate.amountText}</strong>
            <small>{isSellMode ? 'Quantity x price minus fee' : 'Quantity x price plus fee'}</small>
          </div>

          <label className="portfolio-dialog-notes">
            <span>Notes</span>
            <textarea
              value={notes}
              onChange={(event) => {
                setNotes(event.target.value)
                clearError()
              }}
              placeholder="Optional transaction note"
              rows="3"
              disabled={isSubmitting}
            />
          </label>

          {!selectedSecurity && (
            <p className="portfolio-dialog-warning" role="status">
              {isSellMode
                ? 'No held securities are available to sell.'
                : 'Search for a symbol or company and select a security before submitting.'}
            </p>
          )}
          {isSellMode && selectedSecurity && (
            <p className="portfolio-dialog-warning" role="status">
              Available quantity: {formatQuantity(availableQuantity)}
            </p>
          )}
          {error && <p className="portfolio-dialog-error" role="alert">{error}</p>}

          <div className="portfolio-dialog-actions">
            <button className="is-secondary" type="button" onClick={onClose} disabled={isSubmitting}>Cancel</button>
            <button className="is-primary" type="submit" disabled={!selectedSecurity || isSubmitting}>
              {isSubmitting ? 'Submitting...' : 'Submit Transaction'}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}
