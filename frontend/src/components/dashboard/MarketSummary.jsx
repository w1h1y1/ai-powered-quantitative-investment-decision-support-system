import Sparkline from './Sparkline'

const skeletonItems = ['SPY', 'ONEQ', 'DIA', 'BTC/USD']

function MarketSummaryCard({ item }) {
  const isAvailable = item.dataStatus === 'ok'
  const hasSparkline = isAvailable && item.sparkline.length > 1

  return (
    <article className={`market-card ${isAvailable ? '' : 'is-unavailable'}`.trim()}>
      <div className="market-card-header">
        <span className="market-symbol" style={{ '--symbol-color': item.color }}>{item.symbol}</span>
        <span className="market-name">{item.name}</span>
      </div>
      <div className="market-card-body">
        <div>
          <strong>{item.value}</strong>
          <p className={`market-change is-${item.direction}`}>
            {item.change} <span>{item.percent}</span>
          </p>
          {!isAvailable && item.error && (
            <span className="market-card-error">{item.error}</span>
          )}
        </div>
        {hasSparkline ? (
          <Sparkline values={item.sparkline.map((point) => point.close)} color={item.color} />
        ) : (
          <div className="sparkline sparkline-placeholder" aria-hidden="true" />
        )}
      </div>
    </article>
  )
}

function MarketSummarySkeleton() {
  return skeletonItems.map((symbol) => (
    <article className="market-card is-loading" key={symbol}>
      <div className="market-card-header">
        <span className="market-symbol">{symbol}</span>
        <span className="market-skeleton-line is-name" />
      </div>
      <div className="market-card-body">
        <div>
          <span className="market-skeleton-line is-price" />
          <span className="market-skeleton-line is-change" />
        </div>
        <span className="sparkline sparkline-placeholder" aria-hidden="true" />
      </div>
    </article>
  ))
}

export default function MarketSummary({
  error = '',
  isLoading = false,
  items = [],
  lastUpdatedLabel = 'Last updated unavailable',
  statusLabel = 'Latest Market Data',
}) {
  return (
    <section className="market-summary" aria-labelledby="market-summary-title">
      <div className="section-heading">
        <div>
          <p>Global markets</p>
          <h2 id="market-summary-title">Market Summary</h2>
        </div>
        <div className="demo-data-status" aria-label={`${statusLabel}, ${lastUpdatedLabel}`}>
          <strong>{statusLabel}</strong>
          <span>{isLoading ? 'Updating...' : lastUpdatedLabel}</span>
        </div>
      </div>

      {error && !isLoading && (
        <div className="market-summary-error" role="alert">
          {error}
        </div>
      )}

      <div className="market-card-grid">
        {isLoading ? <MarketSummarySkeleton /> : items.map((item) => (
          <MarketSummaryCard item={item} key={item.symbol} />
        ))}
      </div>
    </section>
  )
}
