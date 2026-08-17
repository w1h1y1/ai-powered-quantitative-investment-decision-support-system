import { useEffect, useState } from 'react'
import {
  formatMarketDate,
  formatNumber,
  formatPercent,
  formatPercentile,
  formatRegimeLabel,
  formatUnavailableReason,
} from './marketRegimeModel'

function Metric({ label, tone = '', value }) {
  return (
    <div className="market-regime-metric">
      <span>{label}</span>
      <strong className={tone ? `is-${tone}` : ''}>{value}</strong>
    </div>
  )
}

function RegimeBadge({ regime }) {
  const tone = regime === 'bullish_trend'
    ? 'positive'
    : regime === 'bearish_trend'
      ? 'negative'
      : regime === 'high_volatility'
        ? 'warning'
        : 'neutral'
  return <strong className={`market-regime-context-badge is-${tone}`}>{formatRegimeLabel(regime)}</strong>
}

function ContextUnavailable({ reason }) {
  return <span className="market-regime-context-unavailable">{formatUnavailableReason(reason)}</span>
}

function LoadingState({ symbol }) {
  return (
    <section className="market-panel market-regime-panel" aria-busy="true" aria-live="polite">
      <div className="market-panel-header market-regime-header">
        <div>
          <p>Market Regime</p>
          <h2>Loading market regime for {symbol}...</h2>
        </div>
      </div>
      <div className="market-regime-skeleton" aria-hidden="true">
        <i />
        <i />
        <i />
        <i />
      </div>
    </section>
  )
}

function ErrorState({ error, onRetry, symbol }) {
  return (
    <section className="market-panel market-regime-panel market-regime-message" aria-live="assertive" role="alert">
      <div>
        <p>Market Regime</p>
        <h2>Market regime temporarily unavailable</h2>
        <span>{error || `Unable to load market regime for ${symbol}.`}</span>
      </div>
      {onRetry && <button type="button" onClick={onRetry}>Retry</button>}
    </section>
  )
}

function UnavailableState({ regime }) {
  return (
    <section className="market-panel market-regime-panel market-regime-message" aria-live="polite">
      <div>
        <p>Market Regime</p>
        <h2>Market regime unavailable for {regime.symbol}</h2>
        <span>{regime.unavailableReason}</span>
      </div>
      <div className="market-regime-unavailable-value">N/A</div>
    </section>
  )
}

export default function MarketRegimePanel({ error, isLoading, onRetry, regime, symbol }) {
  const [showAllExplanations, setShowAllExplanations] = useState(false)

  useEffect(() => {
    setShowAllExplanations(false)
  }, [regime?.symbol])

  if (isLoading) return <LoadingState symbol={symbol} />
  if (error) return <ErrorState error={error} onRetry={onRetry} symbol={symbol} />
  if (!regime) return null
  if (!regime.available) return <UnavailableState regime={regime} />

  const explanations = showAllExplanations
    ? regime.explanations
    : regime.explanations.slice(0, 5)
  const context = regime.marketContext
  const relativeStrength = regime.relativeStrength

  return (
    <section className={`market-panel market-regime-panel regime-${regime.regimeTone}`} aria-live="polite">
      <div className="market-panel-header market-regime-header">
        <div>
          <p>Market Regime</p>
          <div className="market-regime-title-row">
            <h2>{regime.symbol}</h2>
            <strong className={`market-regime-label is-${regime.regimeTone}`}>
              {regime.regimeLabel}
            </strong>
            <span className="market-regime-confidence">
              Confidence: {regime.confidence}
              {regime.confidenceScore !== null && ` · ${formatPercent(regime.confidenceScore, { digits: 0 })}`}
            </span>
          </div>
          {regime.explanations[0] && (
            <span className="market-regime-summary">{regime.explanations[0]}</span>
          )}
        </div>
      </div>

      <div className="market-regime-signal-grid">
        <article className="market-regime-signal-card">
          <header><span>01</span><h3>Trend</h3></header>
          <Metric label="Direction" tone={regime.trend.tone} value={regime.trend.direction} />
          <Metric label="Strength" value={regime.trend.strength} />
          <Metric label="ADX" value={formatNumber(regime.trend.adx)} />
        </article>

        <article className="market-regime-signal-card">
          <header><span>02</span><h3>Momentum</h3></header>
          <Metric label="Signal" tone={regime.momentum.tone} value={regime.momentum.signal} />
          <Metric label="RSI" value={formatNumber(regime.momentum.rsi)} />
          <Metric label="MACD Histogram" value={formatNumber(regime.momentum.macdHistogram, 4)} />
          <Metric label="20D Return" tone={regime.momentum.return20d > 0 ? 'positive' : regime.momentum.return20d < 0 ? 'negative' : ''} value={formatPercent(regime.momentum.return20d, { signed: true })} />
          <Metric label="60D Return" tone={regime.momentum.return60d > 0 ? 'positive' : regime.momentum.return60d < 0 ? 'negative' : ''} value={formatPercent(regime.momentum.return60d, { signed: true })} />
        </article>

        <article className="market-regime-signal-card">
          <header><span>03</span><h3>Volatility</h3></header>
          <Metric label="ATR %" value={formatPercent(regime.volatility.atrPercent)} />
          <Metric label="Realized Volatility (20D)" value={formatPercent(regime.volatility.realized20d)} />
          <Metric
            label="Historical Percentile"
            value={regime.volatility.percentileAvailable ? formatPercentile(regime.volatility.percentile) : 'N/A'}
          />
        </article>

        <article className="market-regime-signal-card">
          <header><span>04</span><h3>Range</h3></header>
          <Metric label="Condition" value={regime.range.condition} />
          <Metric label="Choppiness Index" value={formatNumber(regime.range.choppiness)} />
          <Metric label="Range Score" value={formatPercent(regime.range.score)} />
        </article>
      </div>

      <div className="market-regime-detail-grid">
        <article className="market-regime-detail-card">
          <header>
            <p>Context</p>
            <h3>Market Context</h3>
          </header>
          <div className="market-regime-context-row">
            <span>Broad Market ({context.broadMarket})</span>
            {context.broadMarketAvailable
              ? <RegimeBadge regime={context.spyRegime} />
              : <ContextUnavailable reason={context.broadMarketReason} />}
          </div>
          <div className="market-regime-context-row">
            <span>{context.sector} ({context.sectorBenchmark})</span>
            {context.sectorAvailable
              ? <RegimeBadge regime={context.sectorRegime} />
              : <ContextUnavailable reason={context.sectorReason} />}
          </div>
          <div className="market-regime-context-row">
            <span>Confirmation Score</span>
            <strong>{formatPercent(context.confirmationScore, { digits: 0 })}</strong>
          </div>
        </article>

        <article className="market-regime-detail-card">
          <header>
            <p>Performance</p>
            <h3>Relative Strength</h3>
          </header>
          <div className="market-regime-strength-grid">
            <Metric label="vs SPY (20D)" tone={relativeStrength.vsSpy20d > 0 ? 'positive' : relativeStrength.vsSpy20d < 0 ? 'negative' : ''} value={formatPercent(relativeStrength.vsSpy20d, { signed: true })} />
            <Metric label="vs SPY (60D)" tone={relativeStrength.vsSpy60d > 0 ? 'positive' : relativeStrength.vsSpy60d < 0 ? 'negative' : ''} value={formatPercent(relativeStrength.vsSpy60d, { signed: true })} />
            <Metric label={`vs ${context.sectorBenchmark} (20D)`} tone={relativeStrength.vsSector20d > 0 ? 'positive' : relativeStrength.vsSector20d < 0 ? 'negative' : ''} value={formatPercent(relativeStrength.vsSector20d, { signed: true })} />
            <Metric label={`vs ${context.sectorBenchmark} (60D)`} tone={relativeStrength.vsSector60d > 0 ? 'positive' : relativeStrength.vsSector60d < 0 ? 'negative' : ''} value={formatPercent(relativeStrength.vsSector60d, { signed: true })} />
          </div>
        </article>

        <article className="market-regime-detail-card market-regime-explanation-card">
          <header>
            <p>Evidence</p>
            <h3>Why This Regime</h3>
          </header>
          {explanations.length ? (
            <ol>
              {explanations.map((explanation, index) => (
                <li key={`${index}-${explanation}`}>{explanation}</li>
              ))}
            </ol>
          ) : (
            <span className="market-regime-context-unavailable">No explanation was returned.</span>
          )}
          {regime.explanations.length > 5 && (
            <button type="button" onClick={() => setShowAllExplanations((current) => !current)}>
              {showAllExplanations ? 'Show less' : `Show ${regime.explanations.length - 5} more`}
            </button>
          )}
        </article>
      </div>

      <footer className="market-regime-footer">
        <span>Data through {formatMarketDate(regime.freshness.latestMarketDate)}</span>
        <span>{regime.freshness.source}</span>
        <span>{regime.freshness.fetchedFromProvider ? 'Refreshed from provider' : 'Reused cached data'}</span>
      </footer>
    </section>
  )
}
