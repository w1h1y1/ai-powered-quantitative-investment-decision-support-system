import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { AuthProvider } from './context/AuthContext'
import './styles/dashboard.css'
import './styles/dashboard-content.css'
import './styles/market-analysis.css'
import './styles/watchlist.css'
import './styles/portfolio.css'
import './styles/backtest.css'
import './styles/ai-insights.css'
import './styles/prediction-lab.css'
import './styles/auth.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <App />
    </AuthProvider>
  </StrictMode>,
)
