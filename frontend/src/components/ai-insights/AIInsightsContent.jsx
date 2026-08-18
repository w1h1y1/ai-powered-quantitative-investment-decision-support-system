import { useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../Icon'
import SecuritySearchSelect from '../security/SecuritySearchSelect'
import { normalizeSecuritySearchOption } from '../security/securitySearchModel'
import {
  formatAnalysisEnumLabel,
  formatRatioAsPercent,
} from './aiInsightsFormatting'
import { agentAnalysisApi } from '../../services/agentAnalysisApi'
import { securityApi } from '../../services/securityApi'

function SectionCard({ children, eyebrow, title }) {
  return (
    <section className="ai-insights-card" aria-labelledby={`ai-${title}`}>
      <div className="ai-insights-card-heading">
        <div>
          <p>{eyebrow}</p>
          <h2 id={`ai-${title}`}>{title}</h2>
        </div>
      </div>
      {children}
    </section>
  )
}

export function EmptyState({ symbol }) {
  return (
    <section className="ai-insights-card ai-insights-empty-card" aria-labelledby="ai-insights-empty-title">
      <span className="ai-insights-empty-icon" aria-hidden="true">
        <Icon name="insights" />
      </span>
      <h2 id="ai-insights-empty-title">No AI analysis generated yet.</h2>
      <p>
        {symbol
          ? `Generate AI Analysis to review ${symbol} market, technical, portfolio, and backtest context.`
          : 'Select an asset and generate an AI analysis to review market, technical, portfolio, and backtest context.'}
      </p>
    </section>
  )
}

export function LoadingState() {
  return (
    <section className="ai-insights-card ai-insights-empty-card" aria-live="polite" aria-busy="true">
      <i className="ai-insights-spinner is-large" aria-hidden="true" />
      <h2>Generating AI analysis...</h2>
      <p>Building deterministic context and requesting a structured explanation.</p>
    </section>
  )
}

export function UnavailableState({ reason }) {
  return (
    <section className="ai-insights-card ai-insights-state-card" aria-live="polite">
      <h2>AI analysis is currently unavailable.</h2>
      <p>{reason || 'The analysis service could not produce a result.'}</p>
    </section>
  )
}

export function ErrorState({ message }) {
  return (
    <section className="ai-insights-card ai-insights-state-card" role="alert">
      <h2>Unable to generate AI analysis.</h2>
      <p>{message || 'Please try again.'}</p>
    </section>
  )
}

function Metric({ label, value }) {
  return (
    <div className="ai-insights-metric">
      <span>{label}</span>
      <strong>{value ?? '—'}</strong>
    </div>
  )
}

export function DecisionSummaryCard({ analysis }) {
  const decision = analysis.decision_summary || {}
  return (
    <SectionCard eyebrow="Decision" title="AI Decision Summary">
      <div className="ai-insights-decision-grid">
        <Metric label="Stance" value={decision.stance || '—'} />
        <Metric label="Confidence" value={decision.confidence || '—'} />
        <Metric label="Suggested Approach" value={decision.suggested_approach || '—'} />
        <Metric label="Suitable Strategy" value={decision.suitable_strategy || '—'} />
        <Metric label="Time Horizon" value={decision.time_horizon || '—'} />
      </div>
      {decision.key_reasons?.length ? (
        <div className="ai-insights-decision-reasons">
          <h3>Key Reasons</h3>
          <ul>
            {decision.key_reasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        </div>
      ) : null}
      {decision.main_risk ? (
        <div className="ai-insights-main-risk">
          <h3>Main Risk</h3>
          <p>{decision.main_risk}</p>
        </div>
      ) : null}
    </SectionCard>
  )
}

export function OverviewCard({ analysis, metadata }) {
  return (
    <SectionCard eyebrow="Summary" title="Analysis Overview">
      <div className="ai-insights-overview-grid">
        <Metric label="Asset" value={analysis.symbol} />
        <Metric label="As of" value={metadata?.as_of_date ?? '—'} />
        <Metric label="Market Regime" value={formatAnalysisEnumLabel(analysis.market_view?.regime)} />
        <Metric label="Direction" value={analysis.market_view?.direction} />
        <Metric label="Confirmation" value={analysis.market_context_view?.confirmation_level} />
      </div>
    </SectionCard>
  )
}

export function MarketViewCard({ analysis }) {
  return (
    <SectionCard eyebrow="Regime" title="Market View">
      <Metric label="Regime" value={formatAnalysisEnumLabel(analysis.market_view?.regime)} />
      <Metric label="Direction" value={analysis.market_view?.direction} />
      <p className="ai-insights-card-copy">{analysis.market_view?.summary}</p>
    </SectionCard>
  )
}

export function TechnicalViewCard({ analysis }) {
  return (
    <SectionCard eyebrow="Indicators" title="Technical Analysis">
      <Metric label="Trend" value={analysis.technical_view?.trend} />
      <Metric label="Momentum" value={analysis.technical_view?.momentum} />
      <Metric label="Volatility" value={analysis.technical_view?.volatility} />
    </SectionCard>
  )
}

export function MarketContextCard({ analysis }) {
  const context = analysis.market_context_view || {}
  return (
    <SectionCard eyebrow="Environment" title="Market Context">
      <div className="ai-insights-context-line">
        <span>Broad Market</span>
        <p>{context.broad_market}</p>
      </div>
      <div className="ai-insights-context-line">
        <span>Sector</span>
        <p>{context.sector}</p>
      </div>
      <div className="ai-insights-context-line">
        <span>Confirmation</span>
        <p>
          <strong>{context.confirmation_level}</strong>
          <small>Score {context.confirmation_score}</small>
        </p>
      </div>
      <p className="ai-insights-card-copy">{context.confirmation}</p>
    </SectionCard>
  )
}

export function PortfolioContextCard({ analysis }) {
  const portfolio = analysis.portfolio_view || {}
  return (
    <SectionCard eyebrow="Position" title="Portfolio Context">
      {portfolio.has_position ? (
        <>
          <Metric label="Current Position" value="Existing Position" />
          <Metric label="Portfolio Weight" value={formatRatioAsPercent(portfolio.portfolio_weight)} />
          <p className="ai-insights-card-copy">{portfolio.exposure_comment}</p>
        </>
      ) : (
        <>
          <Metric label="Current Position" value="No current position" />
          <Metric label="Portfolio Weight" value="0.00%" />
          <p className="ai-insights-card-copy">{portfolio.exposure_comment}</p>
        </>
      )}
    </SectionCard>
  )
}

export function BacktestEvidenceCard({ analysis }) {
  const backtest = analysis.backtest_view || {}
  if (!backtest.available) {
    return (
      <SectionCard eyebrow="Evidence" title="Historical Backtest Evidence">
        <p className="ai-insights-card-copy">Backtest evidence unavailable</p>
      </SectionCard>
    )
  }

  return (
    <SectionCard eyebrow="Evidence" title="Historical Backtest Evidence">
      <p className="ai-insights-card-copy">{backtest.summary}</p>
      <div className="ai-insights-list-block">
        <h3>Strengths</h3>
        <ul>
          {(backtest.strengths || []).map((item) => <li key={item}>{item}</li>)}
        </ul>
      </div>
      <div className="ai-insights-list-block">
        <h3>Risks</h3>
        <ul>
          {(backtest.risks || []).map((item) => <li key={item}>{item}</li>)}
        </ul>
      </div>
    </SectionCard>
  )
}

export function OverallAssessmentCard({ analysis }) {
  return (
    <SectionCard eyebrow="Synthesis" title="Overall Assessment">
      <p className="ai-insights-card-copy">{analysis.overall_assessment}</p>
    </SectionCard>
  )
}

export function RiskFactorsCard({ analysis }) {
  return (
    <SectionCard eyebrow="Risk" title="Risk Factors">
      {analysis.risk_factors?.length ? (
        <ul className="ai-insights-risk-list">
          {analysis.risk_factors.map((item) => <li key={item}>{item}</li>)}
        </ul>
      ) : (
        <p className="ai-insights-card-copy">No additional risk factors were returned.</p>
      )}
    </SectionCard>
  )
}

export function MetadataFooter({ metadata }) {
  return (
    <footer className="ai-insights-metadata">
      <span>
        As of {metadata?.as_of_date || '—'} · {metadata?.provider === 'deepseek' ? 'DeepSeek' : metadata?.provider || '—'} · {metadata?.analysis_version || '—'}
      </span>
    </footer>
  )
}

function getErrorMessage(error) {
  return error?.message || 'Please try again.'
}

export default function AIInsightsContent() {
  const [securities, setSecurities] = useState([])
  const [isSecuritiesLoading, setIsSecuritiesLoading] = useState(true)
  const [isResolvingAsset, setIsResolvingAsset] = useState(false)
  const [securitiesError, setSecuritiesError] = useState('')
  const [selectedSymbol, setSelectedSymbol] = useState('')
  const [analysis, setAnalysis] = useState(null)
  const [analysisUnavailable, setAnalysisUnavailable] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const requestIdRef = useRef(0)

  useEffect(() => {
    let ignore = false
    securityApi.list()
      .then((response) => {
        if (ignore) return
        const nextSecurities = (Array.isArray(response) ? response : [])
          .filter((security) => security?.is_active !== false)
          .map((security) => normalizeSecuritySearchOption(security))
          .filter(Boolean)
        setSecurities(nextSecurities)
        const preferred = nextSecurities.find((item) => item.symbol === 'AAPL') ?? nextSecurities[0]
        setSelectedSymbol(preferred?.symbol ?? '')
      })
      .catch((error) => {
        if (ignore) return
        setSecurities([])
        setSecuritiesError(error?.message || 'Unable to load securities.')
      })
      .finally(() => {
        if (!ignore) setIsSecuritiesLoading(false)
      })
    return () => {
      ignore = true
    }
  }, [])

  const selectedAsset = useMemo(
    () => securities.find((item) => item.symbol === selectedSymbol) ?? null,
    [securities, selectedSymbol],
  )

  const selectAsset = async (asset) => {
    const symbol = asset?.symbol ?? ''
    if (!symbol) return
    setSelectedSymbol(symbol)
    setAnalysis(null)
    setAnalysisUnavailable('')
    setError('')
    requestIdRef.current += 1
    if (asset.id) return

    setIsResolvingAsset(true)
    try {
      const response = await securityApi.resolve(asset)
      const resolved = normalizeSecuritySearchOption(response?.security)
      if (!resolved) {
        setSecuritiesError('Unable to resolve the selected security.')
        return
      }
      setSecurities((current) => [
        ...current.filter((item) => item.symbol !== resolved.symbol),
        resolved,
      ])
      setSelectedSymbol(resolved.symbol)
    } catch (error) {
      setSecuritiesError(error?.message || 'Unable to resolve the selected security.')
    } finally {
      setIsResolvingAsset(false)
    }
  }

  const generateAnalysis = (event) => {
    event.preventDefault()
    const symbol = selectedSymbol
    if (!symbol || isLoading) return

    const requestId = requestIdRef.current + 1
    requestIdRef.current = requestId
    setIsLoading(true)
    setAnalysis(null)
    setAnalysisUnavailable('')
    setError('')

    agentAnalysisApi.analyze({ symbol })
      .then((response) => {
        if (requestIdRef.current !== requestId || symbol !== selectedSymbol) return
        if (response?.analysis_status === 'unavailable') {
          setAnalysisUnavailable(response.unavailable_reason || 'AI analysis is currently unavailable.')
          return
        }
        if (!response?.analysis) {
          setError('The analysis response was empty.')
          return
        }
        setAnalysis({ ...response.analysis, symbol, metadata: response.metadata })
      })
      .catch((error) => {
        if (requestIdRef.current !== requestId || symbol !== selectedSymbol) return
        setError(getErrorMessage(error))
      })
      .finally(() => {
        if (requestIdRef.current === requestId) setIsLoading(false)
      })
  }

  return (
    <main className="main-content ai-insights-page-main">
      <section className="ai-insights-page-heading" aria-labelledby="ai-insights-page-title">
        <div>
          <p>Decision support</p>
          <h2 id="ai-insights-page-title">AI Insights</h2>
          <span>AI-powered quantitative market analysis based on market regime, technical indicators, portfolio context, and historical backtest evidence.</span>
        </div>
        <div className="demo-data-status" aria-label="AI analysis status">
          <strong>DeepSeek Analysis</strong>
          <span>Structured decision-support</span>
        </div>
      </section>

      <section className="ai-insights-config-card" aria-labelledby="ai-insights-config-title">
        <div className="ai-insights-config-heading">
          <p>Configuration</p>
          <h2 id="ai-insights-config-title">Analysis Setup</h2>
        </div>
        <div className="ai-insights-config-row">
          <label className="ai-insights-field">
            <span>Asset</span>
            <SecuritySearchSelect
              id="ai-insights-asset"
              localSecurities={securities}
              selectedSecurity={selectedAsset}
              onSelect={selectAsset}
            disabled={isSecuritiesLoading || isLoading || isResolvingAsset}
              clearSelectionOnEdit={false}
            />
            {selectedAsset && (
              <div className="ai-insights-selected-asset">
                <strong>{selectedAsset.symbol} — {selectedAsset.name}</strong>
                <span>{selectedAsset.type}</span>
              </div>
            )}
          </label>
          <button
            className="ai-insights-generate-button"
            type="button"
            disabled={!selectedSymbol || isLoading || isSecuritiesLoading || isResolvingAsset}
            onClick={generateAnalysis}
          >
            {isLoading ? 'Analyzing...' : 'Generate AI Analysis'}
          </button>
        </div>
        {securitiesError && <p className="ai-insights-config-error" role="alert">{securitiesError}</p>}
      </section>

      <div className="ai-insights-result-region">
        {isLoading ? (
          <LoadingState />
        ) : analysisUnavailable ? (
          <UnavailableState reason={analysisUnavailable} />
        ) : error ? (
          <ErrorState message={error} />
        ) : analysis ? (
          <>
            <DecisionSummaryCard analysis={analysis} />
            <OverviewCard analysis={analysis} metadata={analysis.metadata} />
            <div className="ai-insights-analysis-grid">
              <MarketViewCard analysis={analysis} />
              <TechnicalViewCard analysis={analysis} />
              <MarketContextCard analysis={analysis} />
              <PortfolioContextCard analysis={analysis} />
              <BacktestEvidenceCard analysis={analysis} />
              <RiskFactorsCard analysis={analysis} />
            </div>
            <OverallAssessmentCard analysis={analysis} />
            <MetadataFooter metadata={analysis.metadata} />
            <aside className="ai-insights-disclaimer" aria-label="AI analysis risk disclosure">
              <Icon name="shield" />
              <span>AI-generated decision support based on available system data. Historical performance does not guarantee future results.</span>
            </aside>
          </>
        ) : (
          <EmptyState symbol={selectedSymbol} />
        )}
      </div>
    </main>
  )
}
