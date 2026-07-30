import Icon from './Icon'

export default function Sidebar({ activeSection, items, onSelect, systemStatus }) {
  return (
    <aside className="sidebar" aria-label="Primary navigation">
      <button className="brand" type="button" onClick={() => onSelect('dashboard')} aria-label="AI Quant dashboard">
        <span className="brand-mark" aria-hidden="true">
          <Icon name="brand" />
        </span>
        <span className="brand-copy">
          <strong>AI Quant</strong>
          <small>Investment Intelligence</small>
        </span>
      </button>

      <nav className="sidebar-nav">
        <p className="nav-label">Workspace</p>
        <ul>
          {items.map((item) => {
            const isActive = item.id === activeSection

            return (
              <li key={item.id}>
                <button
                  className={`nav-link${isActive ? ' is-active' : ''}`}
                  type="button"
                  onClick={() => onSelect(item.id)}
                  aria-current={isActive ? 'page' : undefined}
                  aria-label={item.label}
                >
                  <Icon name={item.icon} />
                  <span>{item.label}</span>
                </button>
              </li>
            )
          })}
        </ul>
      </nav>

      <div className="sidebar-footer">
        <span className="status-dot" aria-hidden="true" />
        <span className="status-copy">
          <strong>{systemStatus.label}</strong>
          <small>{systemStatus.detail}</small>
        </span>
      </div>
    </aside>
  )
}
