import { useCallback, useEffect, useMemo, useState } from 'react'
import Icon from '../Icon'
import { portfolioApi } from '../../services/portfolioApi'
import { securityApi } from '../../services/securityApi'
import { transactionApi } from '../../services/transactionApi'
import AssetAllocation from './AssetAllocation'
import HoldingsTable from './HoldingsTable'
import FundingPanel from './FundingPanel'
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
const transactionPageSizeOptions = [10, 25, 50]
const canShowResetTestPortfolio = Boolean(import.meta.env.DEV)

function padDatePart(value) {
  return String(value).padStart(2, '0')
}

function formatLocalDate(value) {
  return `${value.getFullYear()}-${padDatePart(value.getMonth() + 1)}-${padDatePart(value.getDate())}`
}

function addDays(value, days) {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate() + days)
}

function subtractMonths(value, months) {
  const result = new Date(value.getFullYear(), value.getMonth(), 1)
  const targetDay = value.getDate()
  result.setMonth(result.getMonth() - months)
  const lastDayOfTargetMonth = new Date(result.getFullYear(), result.getMonth() + 1, 0).getDate()
  result.setDate(Math.min(targetDay, lastDayOfTargetMonth))
  return result
}

function getQuarterRange(preset, year) {
  const quarterMonthRanges = {
    Q1: [0, 2],
    Q2: [3, 5],
    Q3: [6, 8],
    Q4: [9, 11],
  }
  const [startMonth, endMonth] = quarterMonthRanges[preset] || quarterMonthRanges.Q1
  return {
    startDate: formatLocalDate(new Date(year, startMonth, 1)),
    endDate: formatLocalDate(new Date(year, endMonth + 1, 0)),
  }
}

function getBrowserTransactionTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || ''
  } catch {
    return ''
  }
}

function getTransactionDateRange(filters) {
  const today = new Date()
  const todayString = formatLocalDate(today)
  if (filters.preset === '7D') {
    return { startDate: formatLocalDate(addDays(today, -6)), endDate: todayString }
  }
  if (filters.preset === '1M') {
    return { startDate: formatLocalDate(subtractMonths(today, 1)), endDate: todayString }
  }
  if (filters.preset === '3M') {
    return { startDate: formatLocalDate(subtractMonths(today, 3)), endDate: todayString }
  }
  if (filters.preset === 'YTD') {
    return { startDate: formatLocalDate(new Date(today.getFullYear(), 0, 1)), endDate: todayString }
  }
  if (['Q1', 'Q2', 'Q3', 'Q4'].includes(filters.preset)) {
    return getQuarterRange(filters.preset, filters.year)
  }
  if (filters.preset === 'CUSTOM') {
    return {
      startDate: filters.customStartDate || todayString,
      endDate: filters.customEndDate || todayString,
    }
  }
  return { startDate: todayString, endDate: todayString }
}

function createDefaultTransactionFilters() {
  const todayString = formatLocalDate(new Date())
  return {
    preset: 'TODAY',
    year: new Date().getFullYear(),
    customStartDate: todayString,
    customEndDate: todayString,
    page: 1,
    pageSize: 10,
  }
}

function buildTransactionQuery(filters) {
  const { startDate, endDate } = getTransactionDateRange(filters)
  return {
    start_date: startDate,
    end_date: endDate,
    page: filters.page,
    page_size: filters.pageSize,
    timezone: getBrowserTransactionTimezone(),
  }
}

function normalizeTransactionListResponse(response, filters) {
  if (Array.isArray(response)) {
    return {
      transactions: response,
      pagination: {
        count: response.length,
        next: null,
        previous: null,
        page: filters.page,
        pageSize: filters.pageSize,
      },
    }
  }

  const transactions = Array.isArray(response?.results) ? response.results : []
  return {
    transactions,
    pagination: {
      count: Number.isFinite(Number(response?.count)) ? Number(response.count) : transactions.length,
      next: response?.next || null,
      previous: response?.previous || null,
      page: filters.page,
      pageSize: filters.pageSize,
    },
  }
}

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
  const [transactionPagination, setTransactionPagination] = useState({
    count: 0,
    next: null,
    previous: null,
    page: 1,
    pageSize: 10,
  })
  const [transactionFilters, setTransactionFilters] = useState(createDefaultTransactionFilters)
  const [isTransactionsLoading, setIsTransactionsLoading] = useState(true)
  const [transactionsError, setTransactionsError] = useState('')
  const [dialog, setDialog] = useState(null)
  const [notice, setNotice] = useState('')
  const [holdingActionError, setHoldingActionError] = useState('')
  const [transactionActionError, setTransactionActionError] = useState('')
  const [isResettingPortfolio, setIsResettingPortfolio] = useState(false)
  const [performanceRefreshKey, setPerformanceRefreshKey] = useState(0)

  const loadPortfolioData = useCallback(async ({ showLoading = true } = {}) => {
    if (showLoading) {
      setIsPortfolioLoading(true)
      setPortfolioSummary(null)
      setSecurities([])
    }
    setPortfolioError('')
    try {
      const [summaryResponse, securityResponse] = await Promise.all([
        portfolioApi.summary(),
        securityApi.list(),
      ])
      setPortfolioSummary(normalizePortfolioSummary(summaryResponse))
      setSecurities(Array.isArray(securityResponse) ? securityResponse : [])
    } catch (error) {
      const message = error.message || 'Request failed. Please try again.'
      if (!showLoading) throw new Error(message)
      setPortfolioError(message)
    } finally {
      if (showLoading) setIsPortfolioLoading(false)
    }
  }, [])

  const loadTransactions = useCallback(async ({ showLoading = true } = {}) => {
    if (showLoading) {
      setIsTransactionsLoading(true)
    }
    setTransactionsError('')
    try {
      const response = await transactionApi.list(buildTransactionQuery(transactionFilters))
      const normalizedResponse = normalizeTransactionListResponse(response, transactionFilters)
      setTransactions(normalizedResponse.transactions)
      setTransactionPagination(normalizedResponse.pagination)
    } catch (error) {
      const message = error.message || 'Request failed. Please try again.'
      if (!showLoading) throw new Error(message)
      setTransactionsError(message)
    } finally {
      if (showLoading) setIsTransactionsLoading(false)
    }
  }, [transactionFilters])

  useEffect(() => {
    loadPortfolioData()
  }, [loadPortfolioData])

  useEffect(() => {
    loadTransactions()
  }, [loadTransactions])

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

  const refreshPortfolioSections = useCallback(async () => {
    await Promise.all([
      loadPortfolioData({ showLoading: false }),
      loadTransactions({ showLoading: false }),
    ])
    setPerformanceRefreshKey((value) => value + 1)
  }, [loadPortfolioData, loadTransactions])

  const selectTransactionPreset = useCallback((preset) => {
    setTransactionFilters((currentFilters) => ({
      ...currentFilters,
      preset,
      page: 1,
    }))
  }, [])

  const changeTransactionYear = useCallback((year) => {
    const parsedYear = Number(year)
    if (!Number.isInteger(parsedYear) || parsedYear < 1900 || parsedYear > 2200) return
    setTransactionFilters((currentFilters) => ({
      ...currentFilters,
      year: parsedYear,
      page: 1,
    }))
  }, [])

  const changeCustomTransactionDate = useCallback((field, value) => {
    if (!['customStartDate', 'customEndDate'].includes(field)) return
    setTransactionFilters((currentFilters) => ({
      ...currentFilters,
      [field]: value,
      preset: 'CUSTOM',
      page: 1,
    }))
  }, [])

  const changeTransactionPage = useCallback((page) => {
    const parsedPage = Number(page)
    if (!Number.isInteger(parsedPage) || parsedPage < 1) return
    setTransactionFilters((currentFilters) => ({
      ...currentFilters,
      page: parsedPage,
    }))
  }, [])

  const changeTransactionPageSize = useCallback((pageSize) => {
    const parsedPageSize = Number(pageSize)
    if (!transactionPageSizeOptions.includes(parsedPageSize)) return
    setTransactionFilters((currentFilters) => ({
      ...currentFilters,
      page: 1,
      pageSize: parsedPageSize,
    }))
  }, [])

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
    setTransactionActionError('')
    setDialog({ type: 'trade', transactionType: 'BUY' })
  }

  const openSellDialog = (holding) => {
    setNotice('')
    setHoldingActionError('')
    setTransactionActionError('')
    setDialog({ type: 'trade', transactionType: 'SELL', holding })
  }

  const saveTrade = async (values) => {
    if (!activePortfolio) return 'Create a Portfolio before recording trades.'
    if (isSubmittingTrade) return ''

    setIsSubmittingTrade(true)
    try {
      const result = await submitTradeTransaction({
        transactionApi,
        reloadPortfolioData: () => loadPortfolioData({ showLoading: false }),
        reloadTransactions: () => loadTransactions({ showLoading: false }),
        values: {
          ...values,
          portfolioId: activePortfolio.id,
        },
      })

      if (!result.ok) return result.error

      const security = normalizedSecurities.find((item) => item.id === values.securityId)
      const actionLabel = values.transactionType === 'SELL' ? 'Sell' : 'Buy'
      setNotice(`${actionLabel} transaction recorded${security ? ` for ${security.symbol}` : ''}.`)
      setPerformanceRefreshKey((value) => value + 1)
      return ''
    } finally {
      setIsSubmittingTrade(false)
    }
  }

  const resetTestPortfolio = async () => {
    if (isResettingPortfolio) return
    const confirmed = window.confirm('Reset this test Portfolio? This will delete your transactions and holdings, restore the initial balance, and refresh performance history.')
    if (!confirmed) return

    setNotice('')
    setTransactionActionError('')
    setIsResettingPortfolio(true)
    try {
      await portfolioApi.resetTestData()
      await refreshPortfolioSections()
      setNotice('Test Portfolio reset.')
    } catch (error) {
      setTransactionActionError(error.message || 'Unable to reset the test Portfolio.')
    } finally {
      setIsResettingPortfolio(false)
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
          <span>PostgreSQL summary and market-data pricing</span>
        </div>
      </section>

      <PortfolioOverview summary={portfolio.summary} />

      <FundingPanel
        onRefresh={refreshPortfolioSections}
        remainingLiquidity={portfolio.summary.availableFunds}
      />

      <div className="portfolio-analytics-grid">
        <PortfolioPerformanceChart
          refreshKey={performanceRefreshKey}
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
        actionError={transactionActionError}
        filters={transactionFilters}
        error={transactionsError}
        isLoading={isTransactionsLoading}
        onCustomDateChange={changeCustomTransactionDate}
        onPageChange={changeTransactionPage}
        onPageSizeChange={changeTransactionPageSize}
        onPresetChange={selectTransactionPreset}
        onYearChange={changeTransactionYear}
        isResetting={isResettingPortfolio}
        onReset={canShowResetTestPortfolio ? resetTestPortfolio : undefined}
        pagination={transactionPagination}
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
