export function normalizeNavigationPath(pathname) {
  return pathname.replace(/\/+$/, '') || '/'
}

export function isKnownNavigationPath(pathname, navigationItems) {
  const currentPath = normalizeNavigationPath(pathname)
  return currentPath === '/' || navigationItems.some(
    (item) => item.path && normalizeNavigationPath(item.path) === currentPath,
  )
}

export function resolveNavigationSection(pathname, historyState, navigationItems) {
  const currentPath = normalizeNavigationPath(pathname)
  const routeItem = navigationItems.find(
    (item) => item.path && normalizeNavigationPath(item.path) === currentPath,
  )
  if (routeItem) return routeItem.id

  const stateSection = historyState?.section
  return navigationItems.some((item) => item.id === stateSection) ? stateSection : 'dashboard'
}
