import Icon from './Icon'

export default function Header({ onLogout, pageTitle, user }) {
  return (
    <header className="topbar">
      <div className="page-heading">
        <p>Investment workspace</p>
        <h1>{pageTitle}</h1>
      </div>

      <div className="header-actions">
        <label className="search-box">
          <span className="sr-only">Search</span>
          <Icon name="search" />
          <input type="search" placeholder="Search markets, assets..." aria-label="Search markets and assets" />
        </label>

        <button className="icon-button" type="button" aria-label="Notifications">
          <Icon name="bell" />
          <span className="notification-dot" aria-hidden="true" />
        </button>

        <div className="user-profile" aria-label="Current user">
          <span className="avatar" aria-hidden="true">{user.initials}</span>
          <span className="user-copy">
            <strong>{user.name}</strong>
            <small>{user.workspace}</small>
          </span>
          <Icon name="chevron" className="chevron" />
        </div>

        <button className="logout-button" type="button" onClick={onLogout}>
          <Icon name="logout" />
          <span>Logout</span>
        </button>
      </div>
    </header>
  )
}
