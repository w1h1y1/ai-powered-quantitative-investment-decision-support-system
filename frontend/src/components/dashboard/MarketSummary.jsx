import Sparkline from './Sparkline'

export default function MarketSummary({ items }) {
  return (
    <section className="market-summary" aria-labelledby="market-summary-title">
      <div className="section-heading">
        <div>
          <p>Global markets</p>
          <h2 id="market-summary-title">Market Summary</h2>
        </div>
        <div className="demo-data-status" aria-label="Demo data, last updated at 16:00">
          <strong>Demo Data</strong>
          <span>Last updated: 16:00</span>
        </div>
      </div>

      <div className="market-card-grid">
        {items.map((item) => (
          <article className="market-card" key={item.symbol}>
            <div className="market-card-header">
              <span className="market-symbol" style={{ '--symbol-color': item.color }}>{item.symbol}</span>
              <span className="market-name">{item.name}</span>
            </div>
            <div className="market-card-body">
              <div>
                <strong>{item.value}</strong>
                <p className={`market-change is-${item.direction}`}>
                  <span aria-hidden="true">{item.direction === 'up' ? '↗' : '↘'}</span>
                  {item.change} <span>{item.percent}</span>
                </p>
              </div>
              <Sparkline values={item.trend} color={item.color} />
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
