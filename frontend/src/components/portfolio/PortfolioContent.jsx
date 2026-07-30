import { useCallback, useEffect, useMemo, useState } from 'react'
import Icon from '../Icon'
import { portfolioApi } from '../../services/portfolioApi'
import { securityApi } from '../../services/securityApi'
import { transactionApi } from '../../services/transactionApi'
import AssetAllocation from './AssetAllocation'
import HoldingsTable from './HoldingsTable'
import PortfolioOverview from './PortfolioOverview'
import PortfolioPerformanceChart from './PortfolioPerformanceChart'
import RecentTransactions from './RecentTransactions'
import TradeDialog from './TradeDialog'
import { normalizePortfolioSummary, normalizeSecurity } from './portfolioSummaryModel'
import { submitTradeTransaction } from './tradeWorkflow'

const dateFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
})

function formatPortfolioDate(value) {
  if (!value) return 'Created date unavailable'
  const parsedDate = new Date(value)
  if (Number.isNaN(parsedDate.getTime())) return 'Created date unavailable'
  return `Created ${dateFormatter.format(parsedDate)}`
}

function PortfolioStateCard({ actionLabel, children, icon = 'portfolio', onAction, tone = '' }) {
  return (
    <section className={`portfolio-empty-state portfolio-record-state ${tone}`.trim()}>
      <span className="portfolio-empty-icon" aria-hidden="true"><Icon name={icon} /></span>
      {children}
      {actionLabel && onAction && (
        <button type="button" onClick={onAction}>{actionLabel}</button>
      )}
    </section>
  )
}

function PortfolioSetupCard({ error, isSubmitting, onCreate }) {
  const [name, setName] = useState('')
  const [availableFunds, setAvailableFunds] = useState('')
  const parsedAvailableFunds = Number(availableFunds)
  const canSubmit = name.trim()
    && availableFunds !== ''
    && Number.isFinite(parsedAvailableFunds)
    && parsedAvailableFunds >= 0

  const handleSubmit = (event) => {
    event.preventDefault()
    if (!canSubmit || isSubmitting) return

    onCreate({
      name: name.trim(),
      available_funds: parsedAvailableFunds.toFixed(2),
    })
  }

  return (
    <section className="portfolio-empty-state portfolio-record-state portfolio-setup-state">
      <span className="portfolio-empty-icon" aria-hidden="true"><Icon name="portfolio" /></span>
      <h3>No Portfolio yet.</h3>
      <p>Create a portfolio record to store your account name and remaining liquidity in PostgreSQL.</p>

      <form className="portfolio-setup-form" onSubmit={handleSubmit}>
        <div className="portfolio-setup-grid">
          <label>
            <span>Portfolio Name</span>
            <input
              name="name"
              onChange={(event) => setName(event.target.value)}
              placeholder="Core Portfolio"
              required
              type="text"
              value={name}
            />
          </label>
          <label>
            <span>Initial Remaining Liquidity</span>
            <input
              min="0"
              name="available_funds"
              onChange={(event) => setAvailableFunds(event.target.value)}
              placeholder="0.00"
              required
              step="0.01"
              type="number"
              value={availableFunds}
            />
          </label>
        </div>
        {error && <p className="portfolio-setup-error" role="alert">{error}</p>}
        <button disabled={!canSubmit || isSubmitting} type="submit">
          {isSubmitting ? 'Creating...' : 'Create Portfolio'}
        </button>
      </form>
    </section>
  )
}

export default function PortfolioContent({ onViewAnalysis }) {
  const [portfolioSummary, setPortfolioSummary] = useState(null)
  const [securities, setSecurities] = useState([])
  const [isPortfolioLoading, setIsPortfolioLoading] = useState(true)
  const [portfolioError, setPortfolioError] = useState('')
  const [isCreatingPortfolio, setIsCreatingPortfolio] = useState(false)
  const [createPortfolioError, setCreatePortfolioError] = useState('')
  const [isSubmittingTrade, setIsSubmittingTrade] = useState(false)
  const [transactions, setTransactions] = useState([])
  const [isTransactionsLoading, setIsTransactionsLoading] = useState(true)
  const [transactionsError, setTransactionsError] = useState('')
  const [dialog, setDialog] = useState(null)
  const [notice, setNotice] = useState('')
  const [holdingActionError, setHoldingActionError] = useState('')

  const loadPortfolioData = useCallback(async () => {
    setIsPortfolioLoading(true)
    setPortfolioError('')
    setPortfolioSummary(null)
    setSecurities([])
    try {
      const [summaryResponse, securityResponse] = await Promise.all([
        portfolioApi.summary(),
        securityApi.list(),
      ])
      setPortfolioSummary(normalizePortfolioSummary(summaryResponse))
      setSecurities(Array.isArray(securityResponse) ? securityResponse : [])
    } catch (error) {
      setPortfolioError(error.message || 'Request failed. Please try again.')
    } finally {
      setIsPortfolioLoading(false)
    }
  }, [])

  const loadTransactions = useCallback(async () => {
    setIsTransactionsLoading(true)
    setTransactionsError('')
    setTransactions([])
    try {
      const response = await transactionApi.list()
      setTransactions(Array.isArray(response) ? response : [])
    } catch (error) {
      setTransactionsError(error.message || 'Request failed. Please try again.')
    } finally {
      setIsTransactionsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadPortfolioData()
    loadTransactions()
  }, [loadPortfolioData, loadTransactions])

  const activePortfolio = portfolioSummary ? {
    id: portfolioSummary.portfolioId,
    name: portfolioSummary.portfolioName,
    base_currency: portfolioSummary.baseCurrency,
    created_at: portfolioSummary.portfolioCreatedAt,
  } : null
  const portfolio = portfolioSummary
  const normalizedSecurities = useMemo(
    () => securities.map(normalizeSecurity).filter((security) => security?.isActive),
    [securities],
  )

  const createPortfolio = async (payload) => {
    setCreatePortfolioError('')
    setIsCreatingPortfolio(true)
    try {
      await portfolioApi.create(payload)
      await loadPortfolioData()
    } catch (error) {
      setCreatePortfolioError(error.message || 'Request failed. Please try again.')
    } finally {
      setIsCreatingPortfolio(false)
    }
  }

  const openBuyDialog = () => {
    setNotice('')
    setHoldingActionError('')
    setDialog({ type: 'trade', transactionType: 'BUY' })
  }

  const openSellDialog = (holding) => {
    setNotice('')
    setHoldingActionError('')
    setDialog({ type: 'trade', transactionType: 'SELL', holding })
  }

  const saveTrade = async (values) => {
    if (!activePortfolio) return 'Create a Portfolio before recording trades.'
    if (isSubmittingTrade) return ''

    setIsSubmittingTrade(true)
    try {
      const result = await submitTradeTransaction({
        transactionApi,
        reloadPortfolioData: loadPortfolioData,
        reloadTransactions: loadTransactions,
        values: {
          ...values,
          portfolioId: activePortfolio.id,
        },
      })

      if (!result.ok) return result.error

      const security = normalizedSecurities.find((item) => item.id === values.securityId)
      const actionLabel = values.transactionType === 'SELL' ? 'Sell' : 'Buy'
      setNotice(`${actionLabel} transaction recorded${security ? ` for ${security.symbol}` : ''}.`)
      return ''
    } finally {
      setIsSubmittingTrade(false)
    }
  }

  if (isPortfolioLoading) {
    return (
      <main className="main-content portfolio-page-main">
        <section className="portfolio-page-heading" aria-labelledby="portfolio-page-title">
          <div>
            <p>Investment account</p>
            <h2 id="portfolio-page-title">Portfolio</h2>
            <span>Loading your Portfolio from PostgreSQL.</span>
          </div>
        </section>
        <PortfolioStateCard>
          <h3>Loading Portfolio...</h3>
          <p>Your account record is being loaded from the Django API.</p>
        </PortfolioStateCard>
      </main>
    )
  }

  if (portfolioError) {
    return (
      <main className="main-content portfolio-page-main">
        <section className="portfolio-page-heading" aria-labelledby="portfolio-page-title">
          <div>
            <p>Investment account</p>
            <h2 id="portfolio-page-title">Portfolio</h2>
            <span>Unable to load your Portfolio record.</span>
          </div>
        </section>
        <PortfolioStateCard actionLabel="Retry" onAction={loadPortfolioData} tone="is-error">
          <h3>Portfolio request failed.</h3>
          <p>{portfolioError}</p>
        </PortfolioStateCard>
      </main>
    )
  }

  if (!activePortfolio) {
    return (
      <main className="main-content portfolio-page-main">
        <section className="portfolio-page-heading" aria-labelledby="portfolio-page-title">
          <div>
            <p>Investment account</p>
            <h2 id="portfolio-page-title">Portfolio</h2>
            <span>Create your first Portfolio before connecting holdings and transaction APIs.</span>
          </div>
        </section>
        <PortfolioSetupCard
          error={createPortfolioError}
          isSubmitting={isCreatingPortfolio}
          onCreate={createPortfolio}
        />
      </main>
    )
  }

  // Portfolio Summary, allocation, Holding metrics, and transaction history come from Django.
  return (
    <main className="main-content portfolio-page-main" data-holdings-count={portfolio.holdings.length}>
      <section className="portfolio-page-heading" aria-labelledby="portfolio-page-title">
        <div>
          <p>Investment account</p>
          <h2 id="portfolio-page-title">{activePortfolio.name}</h2>
          <span>{activePortfolio.base_currency} account - {formatPortfolioDate(activePortfolio.created_at)}</span>
        </div>
        <div className="demo-data-status" aria-label="Portfolio data source">
          <strong>Portfolio Data</strong>
          <span>PostgreSQL summary and holdings - Demo pricing</span>
        </div>
      </section>

      <PortfolioOverview summary={portfolio.summary} />

      <div className="portfolio-analytics-grid">
        <PortfolioPerformanceChart
          totalAccountValue={portfolio.summary.totalAccountValue}
          costBasis={portfolio.summary.costBasis}
        />
        <AssetAllocation
          allocation={portfolio.allocation}
          holdingsValue={portfolio.summary.holdingsValue}
        />
      </div>

      {notice && <p className="portfolio-state-notice" role="status">{notice}</p>}
      {holdingActionError && <p className="portfolio-state-error" role="alert">{holdingActionError}</p>}

      <HoldingsTable
        holdings={portfolio.holdings}
        holdingsCount={portfolio.summary.holdingsCount}
        onBuy={openBuyDialog}
        onSell={openSellDialog}
        isActionPending={isSubmittingTrade}
        onViewAnalysis={onViewAnalysis}
      />

      <RecentTransactions
        error={transactionsError}
        isLoading={isTransactionsLoading}
        transactions={transactions}
      />

      {dialog?.type === 'trade' && (
        <TradeDialog
          holding={dialog.holding}
          holdings={portfolio.holdings}
          isSubmitting={isSubmittingTrade}
          onClose={() => setDialog(null)}
          onSave={saveTrade}
          portfolio={activePortfolio}
          securities={normalizedSecurities}
          transactionType={dialog.transactionType}
        />
      )}
    </main>
  )
}
