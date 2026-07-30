import { useEffect, useMemo, useRef, useState } from 'react'

export default function HoldingDialog({
  securities,
  heldSecurityIds,
  holding,
  isSubmitting,
  mode = 'add',
  onSave,
  onClose,
}) {
  const isEditMode = mode === 'edit' && holding
  const availableSecurities = useMemo(
    () => securities.filter((security) => !heldSecurityIds.includes(security.id)),
    [heldSecurityIds, securities],
  )
  const initialSecurity = isEditMode
    ? securities.find((security) => security.id === holding.securityId)
    : availableSecurities[0] ?? securities[0]
  const [selectedSecurityId, setSelectedSecurityId] = useState(initialSecurity ? String(initialSecurity.id) : '')
  const [quantity, setQuantity] = useState(isEditMode ? String(holding.quantity) : '')
  const [averageCost, setAverageCost] = useState(isEditMode ? String(holding.averageCost) : '')
  const [error, setError] = useState('')
  const quantityInputRef = useRef(null)
  const dialogRef = useRef(null)

  const selectedSecurity = securities.find((security) => String(security.id) === selectedSecurityId)
  const isAlreadyHeld = !isEditMode && selectedSecurity
    ? heldSecurityIds.includes(selectedSecurity.id)
    : false

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
      if (event.key === 'Escape') onClose()

      if (event.key === 'Tab') {
        const focusableElements = dialogRef.current?.querySelectorAll(
          'button:not([disabled]), input:not([disabled]), select:not([disabled])',
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
  }, [onClose])

  const handleSubmit = async (event) => {
    event.preventDefault()

    const parsedQuantity = Number(quantity)
    const parsedAverageCost = Number(averageCost)

    if (!isEditMode && !selectedSecurity) {
      setError('Please select a security.')
      return
    }

    if (!Number.isFinite(parsedQuantity) || parsedQuantity <= 0) {
      setError('Quantity must be greater than 0.')
      return
    }

    if (!Number.isFinite(parsedAverageCost) || parsedAverageCost <= 0) {
      setError('Average Cost must be greater than 0.')
      return
    }

    if (!Number.isFinite(parsedQuantity * parsedAverageCost)) {
      setError('Quantity or Average Cost is too large.')
      return
    }

    if (!isEditMode && isAlreadyHeld) {
      setError(`${selectedSecurity.symbol} is already held.`)
      return
    }

    const savedSecurity = isEditMode ? holding : selectedSecurity
    const saveError = await onSave({
      id: isEditMode ? holding.id : undefined,
      securityId: selectedSecurity?.id,
      symbol: savedSecurity.symbol,
      quantity: parsedQuantity.toFixed(6),
      averageCost: parsedAverageCost.toFixed(4),
    })

    if (saveError) {
      setError(saveError)
      return
    }

    onClose()
  }

  return (
    <div className="portfolio-dialog-backdrop" role="presentation">
      <section
        ref={dialogRef}
        className="portfolio-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="holding-dialog-title"
      >
        <div className="portfolio-dialog-header">
          <div>
            <p>Portfolio entry</p>
            <h2 id="holding-dialog-title">{isEditMode ? 'Edit Holding' : 'Holding Entry'}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close holding form">X</button>
        </div>

        <form onSubmit={handleSubmit}>
          {isEditMode ? (
            <div className="portfolio-dialog-asset-summary" aria-label="Holding being edited">
              <span>{holding.symbol}</span>
              <div>
                <strong>{holding.asset}</strong>
                <small>{holding.type} - {holding.currency}</small>
              </div>
            </div>
          ) : securities.length ? (
            <label>
              <span>Security</span>
              <select
                value={selectedSecurityId}
                onChange={(event) => {
                  setSelectedSecurityId(event.target.value)
                  setError('')
                }}
              >
                {securities.map((security) => (
                  <option value={security.id} key={security.id} disabled={heldSecurityIds.includes(security.id)}>
                    {security.symbol} - {security.name} ({security.type})
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <p className="portfolio-dialog-warning" role="status">
              No securities are available. Add securities in Django Admin before creating holdings.
            </p>
          )}

          <div className="portfolio-dialog-form-grid is-numeric">
            <label>
              <span>Quantity</span>
              <input
                ref={quantityInputRef}
                type="number"
                min="0.0001"
                step="0.0001"
                value={quantity}
                onChange={(event) => {
                  setQuantity(event.target.value)
                  setError('')
                }}
                placeholder="0.00"
              />
            </label>
            <label>
              <span>Average Cost</span>
              <input
                type="number"
                min="0.01"
                step="0.01"
                value={averageCost}
                onChange={(event) => {
                  setAverageCost(event.target.value)
                  setError('')
                }}
                placeholder="0.00"
              />
            </label>
          </div>

          {isAlreadyHeld && !error && (
            <p className="portfolio-dialog-warning" role="status">
              {selectedSecurity.symbol} is already held.
            </p>
          )}
          {error && <p className="portfolio-dialog-error" role="alert">{error}</p>}

          <div className="portfolio-dialog-actions">
            <button className="is-secondary" type="button" onClick={onClose}>Cancel</button>
            <button className="is-primary" type="submit" disabled={(!isEditMode && (!securities.length || isAlreadyHeld)) || isSubmitting}>
              {isSubmitting ? (isEditMode ? 'Saving...' : 'Saving...') : (isEditMode ? 'Save Changes' : 'Save Holding')}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}
