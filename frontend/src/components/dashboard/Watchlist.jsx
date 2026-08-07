import Sparkline from './Sparkline'

export default function Watchlist({ error = '', isLoading = false, items, onRetry, onViewAll }) {
  return (
    <section className="dashboard-panel watchlist-panel" aria-labelledby="watchlist-title">
      <div className="panel-header">
        <div>
          <p>Tracked assets</p>
          <h2 id="watchlist-title">Watchlist</h2>
        </div>
        <button className="panel-action" type="button" onClick={onViewAll}>View all</button>
      </div>

      <div className="watchlist-table-wrap">
        <table className="watchlist-table">
          <thead>
            <tr>
              <th scope="col">Asset</th>
              <th scope="col">Price</th>
              <th scope="col">Change</th>
              <th scope="col"><span className="sr-only">Trend</span></th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan="4">Loading your Watchlist...</td>
              </tr>
            ) : error ? (
              <tr>
                <td colSpan="4">
                  {error}
                  {onRetry && (
                    <button className="panel-action" type="button" onClick={onRetry}>Retry</button>
                  )}
                </td>
              </tr>
            ) : items.length ? items.map((item) => (
              <tr key={item.symbol}>
                <td>
                  <span className="watchlist-symbol">{item.symbol}</span>
                  <span className="watchlist-name">{item.name}</span>
                </td>
                <td className="watchlist-price">{item.price}</td>
                <td><span className={`watchlist-change is-${item.direction}`}>{item.change}</span></td>
                <td><Sparkline values={item.trend} color={item.direction === 'up' ? '#2bbf8a' : item.direction === 'down' ? '#ef6a78' : '#9aa3b2'} width={76} height={28} /></td>
              </tr>
            )) : (
              <tr>
                <td colSpan="4">No saved Watchlist securities.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
