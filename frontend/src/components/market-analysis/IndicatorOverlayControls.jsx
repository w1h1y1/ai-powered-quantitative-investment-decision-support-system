import { useMemo } from 'react'
import { getIndicatorSeries } from './chartMath'
import IndicatorInfoTip from './IndicatorInfoTip'

function getRsiSummary(value) {
  if (value >= 70) {
    return {
      status: 'Overbought',
      className: 'is-overbought',
      explanation: 'Momentum is elevated and may be vulnerable to a short-term pullback.',
    }
  }

  if (value <= 30) {
    return {
      status: 'Oversold',
      className: 'is-oversold',
      explanation: 'Momentum is weak and may be approaching a short-term rebound area.',
    }
  }

  return {
    status: 'Neutral',
    className: 'is-neutral',
    explanation: 'Momentum is balanced, with no clear overbought or oversold signal.',
  }
}

export default function IndicatorOverlayControls({ history, options, selectedOverlays, onToggle }) {
  const closes = useMemo(() => history.candles.map((candle) => candle.close), [history.candles])
  const currentRsi = useMemo(() => {
    const indicatorRsi = history.indicators
      ?.map((indicator) => indicator.rsi)
      .findLast((value) => Number.isFinite(value))
    if (Number.isFinite(indicatorRsi)) return indicatorRsi

    const values = getIndicatorSeries('rsi', closes).primary
    return values.findLast((value) => Number.isFinite(value)) ?? 50
  }, [closes, history.indicators])
  const rsiSummary = getRsiSummary(currentRsi)

  return (
    <section className="market-panel technical-panel overlay-panel" aria-labelledby="overlay-title">
      <div className="market-panel-header">
        <div>
          <p>Chart settings</p>
          <h2 id="overlay-title">Indicator Overlays</h2>
        </div>
        <span className="technical-symbol">{selectedOverlays.length} active</span>
      </div>

      <p className="overlay-help">Price chart remains visible with the selected overlays.</p>

      <div className="overlay-switcher" role="group" aria-label="Price chart overlays">
        {options.map((option) => {
          const isActive = selectedOverlays.includes(option.id)
          return (
            <div className="overlay-switcher-row" key={option.id}>
              <button
                className={isActive ? 'is-active' : ''}
                type="button"
                onClick={() => onToggle(option.id)}
                aria-pressed={isActive}
              >
                <i className={`is-${option.id}`} aria-hidden="true" />
                <span><strong>{option.label}</strong><small>{option.fullName}</small></span>
                <b aria-hidden="true">{isActive ? '✓' : '+'}</b>
              </button>
              {option.type === 'bollinger' && (
                <IndicatorInfoTip label="Bollinger Bands (20, 2)" align="right">
                  <ul>
                    <li>Shows price volatility around the moving average</li>
                    <li>Near the upper band may indicate stronger upward momentum</li>
                    <li>Near the lower band may indicate weaker momentum</li>
                  </ul>
                </IndicatorInfoTip>
              )}
            </div>
          )
        })}
      </div>

      <div className={`rsi-summary-card ${rsiSummary.className}`} aria-label="Current RSI summary">
        <div className="rsi-summary-heading">
          <span>RSI (14)</span>
          <strong className="rsi-summary-status">{rsiSummary.status}</strong>
        </div>
        <div className="rsi-summary-value">
          <strong>{currentRsi.toFixed(1)}</strong>
          <span>Current value</span>
        </div>
        <p>{rsiSummary.explanation}</p>
      </div>
    </section>
  )
}
