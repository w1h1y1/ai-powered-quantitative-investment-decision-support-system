import { useId, useState } from 'react'

export default function IndicatorInfoTip({ label, children, align = 'center' }) {
  const [isOpen, setIsOpen] = useState(false)
  const tooltipId = useId()

  return (
    <span
      className={`indicator-info-tip is-${align} ${isOpen ? 'is-open' : ''}`}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setIsOpen(false)
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape') setIsOpen(false)
      }}
    >
      <button
        type="button"
        aria-label={`About ${label}`}
        aria-describedby={tooltipId}
        aria-expanded={isOpen}
        onClick={() => setIsOpen((current) => !current)}
      >
        i
      </button>
      <span className="indicator-info-popover" id={tooltipId} role="tooltip">
        <strong>{label}</strong>
        {children}
      </span>
    </span>
  )
}
