import { useState } from 'react'
import { formatCompactCurrency, formatCurrency, formatPercentage } from './portfolioMath'

const allocationInnerRadiusRatio = 0.68

function createAllocationGradient(allocation) {
  const allocatedAmount = allocation.reduce((total, item) => total + item.amount, 0)
  if (allocatedAmount <= 0) return 'conic-gradient(#e7ebf2 0% 100%)'

  let start = 0
  const stops = allocation.map((item, index) => {
    const end = index === allocation.length - 1 ? 100 : start + item.percentage
    const stop = `${item.color} ${start}% ${end}%`
    start = end
    return stop
  })

  return `conic-gradient(${stops.join(', ')})`
}

export default function AssetAllocation({ allocation, holdingsValue }) {
  const [hoveredPosition, setHoveredPosition] = useState(null)
  const gradient = createAllocationGradient(allocation)
  const hasHoldings = holdingsValue > 0
  const chartLabel = hasHoldings
    ? allocation
      .map((item) => `${item.symbol}, ${item.asset}, ${formatCurrency(item.amount)}, ${formatPercentage(item.percentage)}`)
      .join('; ')
    : 'No current holdings'

  const handleChartPointerMove = (event) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    const radius = Math.min(bounds.width, bounds.height) / 2
    const dx = event.clientX - (bounds.left + bounds.width / 2)
    const dy = event.clientY - (bounds.top + bounds.height / 2)
    const distance = Math.hypot(dx, dy)

    if (!hasHoldings || distance < radius * allocationInnerRadiusRatio || distance > radius) {
      setHoveredPosition(null)
      return
    }

    const pointerPercentage = ((((Math.atan2(dy, dx) * 180) / Math.PI + 450) % 360) / 3.6)
    let cumulativePercentage = 0
    const item = allocation.find((position, index) => {
      cumulativePercentage += position.percentage
      return pointerPercentage <= cumulativePercentage || index === allocation.length - 1
    })

    if (!item) {
      setHoveredPosition(null)
      return
    }

    const placeLeft = event.clientX + 210 > window.innerWidth
    setHoveredPosition({
      item,
      x: placeLeft ? event.clientX - 12 : event.clientX + 12,
      y: Math.min(Math.max(event.clientY, 68), Math.max(window.innerHeight - 68, 68)),
      placeLeft,
    })
  }

  return (
    <section className="portfolio-card portfolio-allocation-panel" aria-labelledby="position-allocation-title">
      <div className="portfolio-card-header">
        <div>
          <p>Current position mix</p>
          <h2 id="position-allocation-title">Position Allocation</h2>
          <span className="portfolio-allocation-basis">Demo pricing from Portfolio Summary API</span>
        </div>
      </div>

      <div className="portfolio-allocation-layout">
        <div
          className={`portfolio-allocation-chart${hasHoldings ? '' : ' is-empty'}`}
          style={{ '--portfolio-allocation-gradient': gradient }}
          role="img"
          aria-label={chartLabel}
          onPointerMove={handleChartPointerMove}
          onPointerLeave={() => setHoveredPosition(null)}
          onPointerCancel={() => setHoveredPosition(null)}
        >
          <div className="portfolio-allocation-center">
            <span>Holdings Value</span>
            <strong>{formatCompactCurrency(holdingsValue)}</strong>
          </div>
          {hoveredPosition && (
            <div
              className={`portfolio-allocation-tooltip${hoveredPosition.placeLeft ? ' is-left' : ''}`}
              style={{
                '--portfolio-tooltip-accent': hoveredPosition.item.color,
                left: hoveredPosition.x,
                top: hoveredPosition.y,
              }}
              role="tooltip"
            >
              <strong>{hoveredPosition.item.symbol}</strong>
              <span>{hoveredPosition.item.asset}</span>
              <b>{formatCurrency(hoveredPosition.item.amount)} - {formatPercentage(hoveredPosition.item.percentage)}</b>
            </div>
          )}
        </div>

        {allocation.length ? (
          <ul className="portfolio-allocation-legend">
            {allocation.map((item) => (
              <li key={item.key}>
                <span className="portfolio-allocation-color" style={{ background: item.color }} aria-hidden="true" />
                <div className="portfolio-allocation-position">
                  <strong>{item.symbol}</strong>
                  <span title={item.asset}>{item.asset}</span>
                </div>
                <div className="portfolio-allocation-values">
                  <strong>{formatCurrency(item.amount)}</strong>
                  <span>{formatPercentage(item.percentage)}</span>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="portfolio-allocation-empty">No positions to allocate.</p>
        )}
      </div>
    </section>
  )
}
