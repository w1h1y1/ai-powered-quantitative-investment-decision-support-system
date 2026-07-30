const iconContent = {
  brand: (
    <>
      <path d="M5 16.5 9.2 12l3.1 2.8L19 7.5" />
      <path d="M15 7.5h4v4" />
    </>
  ),
  dashboard: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="2" />
      <rect x="14" y="3" width="7" height="7" rx="2" />
      <rect x="3" y="14" width="7" height="7" rx="2" />
      <rect x="14" y="14" width="7" height="7" rx="2" />
    </>
  ),
  market: (
    <>
      <path d="M4 19V9" />
      <path d="M10 19V5" />
      <path d="M16 19v-7" />
      <path d="M22 19H2" />
    </>
  ),
  watchlist: (
    <>
      <path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9L12 3Z" />
    </>
  ),
  portfolio: (
    <>
      <path d="M4 7.5h16v11H4z" />
      <path d="M8 7.5V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2.5" />
      <path d="M4 12h16" />
    </>
  ),
  strategy: (
    <>
      <path d="M4 18 9 13l3 3 7-8" />
      <path d="M15 8h4v4" />
      <path d="M4 5v14h16" />
    </>
  ),
  insights: (
    <>
      <path d="M8.5 16.5h7" />
      <path d="M9.5 20h5" />
      <path d="M8.2 13.4A6 6 0 1 1 15.8 13.4c-.8.6-1.3 1.4-1.3 2.1h-5c0-.7-.5-1.5-1.3-2.1Z" />
    </>
  ),
  prediction: (
    <>
      <path d="M3 18.5h18" />
      <path d="M4.5 15.5 8 12l3 2 3.5-5 5 2.5" />
      <path d="M14.5 9 18 6.5l2 2" />
      <path d="M14.5 9v5" strokeDasharray="2 2" />
    </>
  ),
  target: (
    <>
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="4" />
      <path d="M12 8v8" />
      <path d="M8 12h8" />
    </>
  ),
  check: (
    <>
      <path d="M20 6 9 17l-5-5" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3 20 6.5v5.7c0 4.5-3.2 7.5-8 8.8-4.8-1.3-8-4.3-8-8.8V6.5L12 3Z" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  trend: (
    <>
      <path d="M4 17 9 12l3 3 7-8" />
      <path d="M15 7h4v4" />
    </>
  ),
  alert: (
    <>
      <path d="M12 3 22 20H2L12 3Z" />
      <path d="M12 9v5" />
      <path d="M12 17h.01" />
    </>
  ),
  history: (
    <>
      <path d="M4 12a8 8 0 1 0 2.3-5.7" />
      <path d="M4 5v5h5" />
      <path d="M12 8v5l3 2" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-4-4" />
    </>
  ),
  bell: (
    <>
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
      <path d="M10 21h4" />
    </>
  ),
  logout: (
    <>
      <path d="M10 6H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h4" />
      <path d="M14 16l4-4-4-4" />
      <path d="M18 12H9" />
    </>
  ),
  chevron: <path d="m8 10 4 4 4-4" />,
}

export default function Icon({ name, className, title }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
    >
      {title && <title>{title}</title>}
      {iconContent[name]}
    </svg>
  )
}
