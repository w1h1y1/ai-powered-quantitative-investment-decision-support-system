import { useEffect, useRef } from 'react'

export default function DeleteInsightDialog({ insight, onCancel, onConfirm }) {
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
      className="ai-insights-dialog-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onCancel()
      }}
    >
      <div
        className="ai-insights-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="ai-insights-delete-title"
        aria-describedby="ai-insights-delete-description"
        ref={dialogRef}
      >
        <span className="ai-insights-dialog-eyebrow">Delete saved insight</span>
        <h2 id="ai-insights-delete-title">Delete {insight.asset.symbol} insight?</h2>
        <p id="ai-insights-delete-description">
          This removes the saved rule-based insight from local history. This action cannot be undone.
        </p>
        <div className="ai-insights-dialog-actions">
          <button type="button" ref={cancelButtonRef} onClick={onCancel}>Cancel</button>
          <button type="button" className="is-confirm-delete" onClick={onConfirm}>Delete</button>
        </div>
      </div>
    </div>
  )
}
