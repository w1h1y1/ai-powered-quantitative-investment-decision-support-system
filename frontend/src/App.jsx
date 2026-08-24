import { useEffect, useMemo, useState } from 'react'
import Header from './components/Header'
import Icon from './components/Icon'
import ScrollToTop from './components/ScrollToTop'
import Sidebar from './components/Sidebar'
import WorkspaceContent from './components/WorkspaceContent'
import AIInsightsContent from './components/ai-insights/AIInsightsContent'
import BacktestContent from './components/backtest/BacktestContent'
import DashboardContent from './components/dashboard/DashboardContent'
import MarketAnalysisContent from './components/market-analysis/MarketAnalysisContent'
import PortfolioContent from './components/portfolio/PortfolioContent'
import WatchlistContent from './components/watchlist/WatchlistContent'
import { useAuth } from './context/AuthContext'
import AuthPage from './pages/AuthPage'
import {
  dashboardData,
  mockSystemStatus,
  navigationItems,
  workspaceContent,
} from './data/mockData'
import {
  isKnownNavigationPath,
  normalizeNavigationPath as normalizePath,
  resolveNavigationSection,
} from './data/navigationRouting'

function getSectionFromLocation(historyState = window.history.state) {
  return resolveNavigationSection(window.location.pathname, historyState, navigationItems)
}

function isAuthPath(pathname) {
  const currentPath = normalizePath(pathname)
  return currentPath === '/login' || currentPath === '/register'
}

function getAuthModeFromLocation(pathname = window.location.pathname) {
  return normalizePath(pathname) === '/register' ? 'register' : 'login'
}

function getUserInitials(user) {
  const source = user?.username || user?.email || 'User'
  return source
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join('') || 'U'
}

function getHeaderUser(user) {
  return {
    initials: getUserInitials(user),
    name: user?.username || 'User',
    workspace: user?.email || 'Research workspace',
  }
}

function redirectToCanonicalDevelopmentHost() {
  if (!import.meta.env.DEV || typeof window === 'undefined') return
  if (window.location.hostname !== 'localhost') return

  const port = window.location.port || '5173'
  window.location.replace(`http://127.0.0.1:${port}${window.location.pathname}${window.location.search}${window.location.hash}`)
}

redirectToCanonicalDevelopmentHost()

export default function App() {
  const { authError, isAuthenticated, isLoading, login, logout, register, user } = useAuth()
  const [activeSection, setActiveSection] = useState(() => getSectionFromLocation())
  const [authMode, setAuthMode] = useState(() => getAuthModeFromLocation())
  const [selectedAnalysisSymbol, setSelectedAnalysisSymbol] = useState('')

  const activeNavigationItem = useMemo(
    () => navigationItems.find((item) => item.id === activeSection) ?? navigationItems[0],
    [activeSection],
  )

  const activeContent = workspaceContent[activeNavigationItem.id]

  useEffect(() => {
    const initialSection = getSectionFromLocation()
    window.history.replaceState(
      { ...(window.history.state ?? {}), section: initialSection },
      '',
      window.location.href,
    )

    const handlePopState = (event) => {
      setActiveSection(getSectionFromLocation(event.state))
      if (isAuthPath(window.location.pathname)) {
        setAuthMode(getAuthModeFromLocation())
      }
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  useEffect(() => {
    if (isLoading) return
    if (authError && !isAuthenticated) return

    const currentPath = normalizePath(window.location.pathname)

    if (!isAuthenticated) {
      if (!isAuthPath(currentPath)) {
        window.history.replaceState({ authMode: 'login' }, '', '/login')
        setAuthMode('login')
      }
      return
    }

    if (isAuthPath(currentPath)) {
      window.history.replaceState({ section: 'dashboard' }, '', '/')
      setActiveSection('dashboard')
      return
    }

    if (!isKnownNavigationPath(currentPath, navigationItems)) {
      window.history.replaceState({ section: 'dashboard' }, '', '/')
      setActiveSection('dashboard')
    }
  }, [authError, isAuthenticated, isLoading])

  const navigateToSection = (sectionId) => {
    if (!isAuthenticated) {
      navigateToAuth('login')
      return
    }

    const nextItem = navigationItems.find((item) => item.id === sectionId) ?? navigationItems[0]
    const nextPath = nextItem.path ?? '/'
    const isCurrentEntry = activeNavigationItem.id === nextItem.id
      && normalizePath(window.location.pathname) === normalizePath(nextPath)

    if (!isCurrentEntry) {
      window.history.pushState(
        { ...(window.history.state ?? {}), section: nextItem.id },
        '',
        nextPath,
      )
    }
    setActiveSection(nextItem.id)
  }

  const navigateToAuth = (nextMode) => {
    const nextPath = nextMode === 'register' ? '/register' : '/login'
    if (normalizePath(window.location.pathname) !== nextPath) {
      window.history.pushState({ authMode: nextMode }, '', nextPath)
    }
    setAuthMode(nextMode)
  }

  const completeAuthentication = () => {
    window.history.replaceState({ section: 'dashboard' }, '', '/')
    setActiveSection('dashboard')
  }

  const handleLogin = async (credentials) => {
    await login(credentials)
    completeAuthentication()
  }

  const handleRegister = async (payload) => {
    await register(payload)
    completeAuthentication()
  }

  const handleLogout = async () => {
    await logout()
    window.history.replaceState({ authMode: 'login' }, '', '/login')
    setAuthMode('login')
    setActiveSection('dashboard')
  }

  const openMarketAnalysis = (symbol) => {
    setSelectedAnalysisSymbol(symbol)
    navigateToSection('market-analysis')
  }

  if (isLoading) {
    return (
      <main className="auth-screen">
        <section className="auth-panel auth-loading" aria-live="polite">
          <div className="auth-brand">
            <span className="brand-mark" aria-hidden="true">
              <Icon name="brand" />
            </span>
            <span>
              <strong>AI Quant</strong>
              <small>Investment Intelligence</small>
            </span>
          </div>
          <p>Loading account...</p>
        </section>
      </main>
    )
  }

  if (!isAuthenticated) {
    if (authError) {
      return (
        <main className="auth-screen">
          <section className="auth-panel auth-loading" aria-live="polite">
            <div className="auth-brand">
              <span className="brand-mark" aria-hidden="true">
                <Icon name="brand" />
              </span>
              <span>
                <strong>AI Quant</strong>
                <small>Investment Intelligence</small>
              </span>
            </div>
            <div className="auth-heading">
              <p>Server unavailable</p>
              <h1>Unable to verify your session</h1>
            </div>
            <div className="auth-error" role="alert">
              {authError}
            </div>
          </section>
        </main>
      )
    }

    return (
      <AuthPage
        mode={authMode}
        onLogin={handleLogin}
        onModeChange={navigateToAuth}
        onRegister={handleRegister}
      />
    )
  }

  const headerUser = getHeaderUser(user)

  return (
    <div className="app-shell">
      <ScrollToTop
        pathname={normalizePath(window.location.pathname)}
        section={activeNavigationItem.id}
      />
      <Sidebar
        activeSection={activeNavigationItem.id}
        items={navigationItems}
        onSelect={navigateToSection}
        systemStatus={mockSystemStatus}
      />

      <div className="workspace">
        <Header onLogout={handleLogout} pageTitle={activeNavigationItem.label} user={headerUser} />
        {activeNavigationItem.id === 'dashboard' ? (
          <DashboardContent
            data={dashboardData}
            onOpenPortfolio={() => navigateToSection('portfolio')}
            onOpenWatchlist={() => navigateToSection('watchlist')}
          />
        ) : activeNavigationItem.id === 'market-analysis' ? (
          <MarketAnalysisContent
            selectedSymbol={selectedAnalysisSymbol}
            onSelectedSymbolChange={setSelectedAnalysisSymbol}
          />
        ) : activeNavigationItem.id === 'watchlist' ? (
          <WatchlistContent onViewAnalysis={openMarketAnalysis} />
        ) : activeNavigationItem.id === 'portfolio' ? (
          <PortfolioContent key={user?.id ?? 'anonymous'} onViewAnalysis={openMarketAnalysis} />
        ) : activeNavigationItem.id === 'strategy-backtesting' ? (
          <BacktestContent />
        ) : activeNavigationItem.id === 'ai-insights' ? (
          <AIInsightsContent onNavigate={navigateToSection} />
        ) : (
          <WorkspaceContent content={activeContent} />
        )}
      </div>
    </div>
  )
}
