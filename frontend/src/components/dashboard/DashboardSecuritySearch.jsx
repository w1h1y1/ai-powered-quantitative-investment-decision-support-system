import {
  DASHBOARD_SEARCH_MESSAGES,
  dashboardSearchStatus,
} from './dashboardSearchModel'
import { getSecuritySearchKey } from '../security/securitySearchModel'

export default function DashboardSecuritySearch({
  id,
  disabled = false,
  query = '',
  results = [],
  isSearching = false,
  hasSearched = false,
  error = '',
  detail = '',
  notice = '',
  onQueryChange,
  onSearch,
  onSelect,
}) {
  const status = dashboardSearchStatus({ query, results, isSearching, hasSearched, error })
  const resolvedStatus = { ...status, detail: status.kind === 'error' ? detail : '' }
  const showStatus = status.kind !== 'idle'

  return (
    <div className="dashboard-search">
      <div className="dashboard-search-row">
        <input
          id={id}
          type="search"
          value={query}
          placeholder="Search symbol or company name, e.g. AVGO"
          autoComplete="off"
          disabled={disabled}
          aria-label="Search securities"
          onChange={(event) => onQueryChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              onSearch(query)
            }
          }}
        />
        <button
          className="dashboard-search-button"
          type="button"
          disabled={disabled || isSearching}
          onClick={() => onSearch(query)}
        >
          {isSearching ? DASHBOARD_SEARCH_MESSAGES.searching : 'Search'}
        </button>
      </div>

      {showStatus && (
        <p className={`dashboard-search-status${status.kind === 'error' ? ' is-error' : ''}`} role={status.kind === 'error' ? 'alert' : undefined}>
          {resolvedStatus.message}
          {resolvedStatus.detail ? <span className="dashboard-search-detail"> {resolvedStatus.detail}</span> : null}
        </p>
      )}

      {results.length > 0 && (
        <div className="security-search-popover dashboard-search-results">
          <ul role="listbox" aria-label="Security search results">
            {results.map((security, index) => {
              const optionKey = getSecuritySearchKey(security)
              return (
                <li key={`${optionKey}-${index}`} role="option">
                  <button
                    type="button"
                    onClick={() => onSelect(security)}
                  >
                    <span>
                      <strong>{security.symbol}</strong>
                      <small>{security.name}</small>
                    </span>
                    <span className="security-search-meta">
                      <small>
                        {[security.exchange, security.instrument_type].filter(Boolean).join(' · ')}
                      </small>
                      <b className={security.is_local ? 'is-local' : 'is-remote'}>
                        {security.is_local ? 'Local' : 'Remote'}
                      </b>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {notice && results.length > 0 && (
        <p className="dashboard-search-notice">{notice}</p>
      )}
    </div>
  )
}
