import { useEffect, useMemo, useRef, useState } from 'react'
import { formatQuantity } from './portfolioMath'
import { buildTradeEstimate, validateTradeFields } from './tradeWorkflow'

function toDateTimeLocalValue(date = new Date()) {
  const timezoneOffset = date.getTimezoneOffset() * 60000
  return new Date(date.getTime() - timezoneOffset).toISOString().slice(0, 16)
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
  const initialSecurityId = isSellMode && holding
    ? String(holding.securityId)
    : securities[0] ? String(securities[0].id) : ''
  const [selectedSecurityId, setSelectedSecurityId] = useState(initialSecurityId)
  const [quantity, setQuantity] = useState('')
  const [price, setPrice] = useState('')
  const [transactionDate, setTransactionDate] = useState(toDateTimeLocalValue())
  const [fee, setFee] = useState('0')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
  const securitySelectRef = useRef(null)
  const quantityInputRef = useRef(null)
  const priceInputRef = useRef(null)
  const transactionDateInputRef = useRef(null)
  const feeInputRef = useRef(null)
  const dialogRef = useRef(null)
  const submitLockRef = useRef(false)

  const selectedSecurityFromList = securities.find((security) => String(security.id) === selectedSecurityId)
  const selectedSecurity = selectedSecurityFromList ?? (holding ? {
    id: holding.securityId,
    symbol: holding.symbol,
    name: holding.asset,
    type: holding.type,
  } : null)
  const selectedHolding = useMemo(
    () => holding ?? holdings.find((item) => String(item.securityId) === selectedSecurityId),
    [holding, holdings, selectedSecurityId],
  )
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
    securityId: selectedSecurity?.id,
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

  const tradeValues = getTradeValues()
  const tradeEstimate = buildTradeEstimate(tradeValues)

  useEffect(() => {
    const previouslyFocusedElement = document.activeElement
    const previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    quantityInputRef.current?.focus()

    return () => {
      document.body.style.overflow = previousBodyOverflow
      previouslyFocusedElement?.focus()
    }
  }, [])

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

          {isSellMode && selectedSecurity ? (
            <div className="portfolio-dialog-asset-summary is-readonly-security" aria-label="Security being sold">
              <span>{selectedSecurity.symbol}</span>
              <div>
                <strong>{selectedSecurity.name || selectedSecurity.symbol}</strong>
                <small>{selectedSecurity.type || 'Security'} - read-only sell target</small>
              </div>
              <b>{formatQuantity(availableQuantity)}</b>
            </div>
          ) : (
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
                disabled={!securities.length || isSubmitting}
                aria-invalid={fieldErrors.security ? 'true' : 'false'}
                aria-describedby={fieldErrors.security ? 'trade-security-error' : undefined}
              >
                {securities.map((security) => (
                  <option value={security.id} key={security.id}>
                    {security.symbol} - {security.name} ({security.type})
                  </option>
                ))}
              </select>
              {fieldErrors.security && (
                <small className="portfolio-dialog-field-error" id="trade-security-error" role="alert">
                  {fieldErrors.security}
                </small>
              )}
            </label>
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
              No securities are available. Add securities in Django Admin before recording trades.
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
