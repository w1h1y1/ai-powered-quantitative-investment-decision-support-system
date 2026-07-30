import { useEffect, useRef } from 'react'

export default function DeleteForecastDialog({ forecast, onCancel, onConfirm }) {
  const cancelButtonRef = useRef(null)
  const dialogRef = useRef(null)

  useEffect(() => {
    const focusFrame = window.requestAnimationFrame(() => cancelButtonRef.current?.focus())

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCancel()
        return
      }

      if (event.key !== 'Tab') return
      const controls = [...(dialogRef.current?.querySelectorAll('button') ?? [])]
      if (!controls.length) return

      const firstControl = controls[0]
      const lastControl = controls.at(-1)
      if (!dialogRef.current?.contains(document.activeElement)) {
        event.preventDefault()
        firstControl.focus()
      } else if (event.shiftKey && document.activeElement === firstControl) {
        event.preventDefault()
        lastControl.focus()
      } else if (!event.shiftKey && document.activeElement === lastControl) {
        event.preventDefault()
        firstControl.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [onCancel])

  return (
    <div
      className="prediction-dialog-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onCancel()
      }}
    >
      <div
        className="prediction-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="prediction-delete-title"
        aria-describedby="prediction-delete-description"
        ref={dialogRef}
      >
        <span className="prediction-dialog-eyebrow">Delete saved forecast</span>
        <h2 id="prediction-delete-title">Delete {forecast.asset.symbol} forecast?</h2>
        <p id="prediction-delete-description">
          This removes the saved rule-based forecast from local history. This action cannot be undone.
        </p>
        <div className="prediction-dialog-actions">
          <button type="button" ref={cancelButtonRef} onClick={onCancel}>Cancel</button>
          <button type="button" className="is-confirm-delete" onClick={onConfirm}>Delete</button>
        </div>
      </div>
    </div>
  )
}

