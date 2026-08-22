import { useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../Icon'
import SecuritySearchSelect from '../security/SecuritySearchSelect'
import { normalizeSecuritySearchOption } from '../security/securitySearchModel'
import {
  formatAnalysisEnumLabel,
  formatGeneratedAt,
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
      <p>Building deterministic evidence and requesting an independent structured AI assessment.</p>
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

function strategyDisplayName(analysis, strategyId) {
  const definition = (analysis.available_strategies || [])
    .find((item) => item?.id === strategyId)
  return definition?.name || formatAnalysisEnumLabel(strategyId)
}

function independentAssessment(analysis) {
  return analysis.llm_independent_assessment || null
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

export function FinalAIAssessmentCard({ analysis }) {
  const independent = independentAssessment(analysis)
  const assessment = independent?.llm_market_assessment || analysis.final_market_assessment || {}
  return (
    <SectionCard eyebrow="Independent judgment" title="Independent AI Assessment">
      <div className="ai-insights-decision-grid">
        <Metric label="Market Regime" value={formatAnalysisEnumLabel(assessment.regime)} />
        <Metric label="Direction" value={formatAnalysisEnumLabel(assessment.direction)} />
        <Metric label="Confidence" value={formatRatioAsPercent(assessment.confidence)} />
      </div>
      <p className="ai-insights-card-copy">{assessment.summary || 'No final summary was provided.'}</p>
      {analysis.backend_suggestion_exposed_to_llm === false ? (
        <p className="ai-insights-card-copy">
          The AI assessment was generated independently without receiving the backend’s suggested strategy.
        </p>
      ) : null}
    </SectionCard>
  )
}

export function FinalStrategyAssessmentCard({ analysis }) {
  const independent = independentAssessment(analysis)
  const assessment = independent?.llm_final_strategy_assessment || analysis.final_strategy_assessment || {}
  return (
    <SectionCard eyebrow="Independent selection" title="AI Strategy Assessment">
      <Metric label="AI Selected Strategy" value={strategyDisplayName(analysis, assessment.selected_strategy)} />
      {assessment.confidence !== undefined ? (
        <Metric label="Confidence" value={formatRatioAsPercent(assessment.confidence)} />
      ) : null}
      <Metric label="Suitability" value={formatAnalysisEnumLabel(assessment.suitability)} />
      <p className="ai-insights-card-copy">{assessment.reason || 'No strategy rationale was provided.'}</p>
      {assessment.why_not_alternatives?.length ? (
        <div className="ai-insights-list-block">
          <h3>Why Not the Alternatives</h3>
          <ul className="ai-insights-risk-list">
            {assessment.why_not_alternatives.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      ) : null}
    </SectionCard>
  )
}

function ComparisonFactors({ factors, emptyText }) {
  if (!factors?.length) return <p className="ai-insights-card-copy">{emptyText}</p>
  return (
    <div className="ai-insights-list-block">
      {factors.map((item, index) => (
        <div className="ai-insights-context-line" key={`${item.factor}-${index}`}>
          <span>{item.factor}</span>
          <p><strong>{String(item.value)}</strong><small>{item.interpretation}</small></p>
        </div>
      ))}
    </div>
  )
}

export function StrategyComparisonCard({ analysis }) {
  const independent = independentAssessment(analysis)
  const comparison = independent?.llm_strategy_comparison || analysis.strategy_comparison || {}
  const catalog = analysis.available_strategies?.length
    ? analysis.available_strategies
    : Object.keys(comparison).map((id) => ({ id, name: formatAnalysisEnumLabel(id) }))
  if (!catalog.length) return null

  return (
    <SectionCard eyebrow="Candidate evaluation" title="Strategy Comparison">
      <Metric
        label="Comparable Backtest Evidence"
        value={(independent?.backtest_evidence_available ?? analysis.backtest_evidence_available) ? 'Available' : 'Unavailable'}
      />
      <div className="ai-insights-strategy-comparison-grid">
        {catalog.map((definition) => {
          const candidate = comparison[definition.id] || {}
          return (
            <article className="ai-insights-strategy-candidate" key={definition.id}>
              <span>{definition.name || formatAnalysisEnumLabel(definition.id)}</span>
              <div>
                <p><strong>{formatAnalysisEnumLabel(candidate.suitability) || '—'}</strong></p>
                <h3>Supporting Factors</h3>
                <ComparisonFactors
                  factors={candidate.supporting_factors}
                  emptyText="No verified supporting factor was reported."
                />
                <h3>Conflicting Factors</h3>
                <ComparisonFactors
                  factors={candidate.conflicting_factors}
                  emptyText="No verified conflicting factor was reported."
                />
              </div>
            </article>
          )
        })}
      </div>
    </SectionCard>
  )
}

export function QuantitativeAssessmentCard({ analysis }) {
  const assessment = analysis.backend_quantitative_assessment || analysis.quantitative_assessment || {}
  return (
    <SectionCard eyebrow="Deterministic engine" title="Quantitative Engine Assessment">
      <div className="ai-insights-decision-grid">
        <Metric label="Preliminary Regime" value={formatAnalysisEnumLabel(assessment.preliminary_regime)} />
        <Metric label="Suggested Strategy" value={formatAnalysisEnumLabel(assessment.suggested_strategy)} />
        <Metric label="Confidence" value={formatRatioAsPercent(assessment.confidence)} />
        <Metric label="Risk Off" value={assessment.risk_off ? 'Yes' : 'No'} />
        <Metric label="Allow New Long" value={assessment.allow_new_long ? 'Yes' : 'No'} />
      </div>
      {assessment.explanation?.length ? (
        <ul className="ai-insights-risk-list">
          {assessment.explanation.map((item) => <li key={item}>{item}</li>)}
        </ul>
      ) : null}
    </SectionCard>
  )
}

export function QuantitativeAgreementCard({ analysis }) {
  const agreement = analysis.quantitative_agreement || {}
  return (
    <SectionCard eyebrow="Comparison" title="Agreement with Quantitative Engine">
      <Metric label="Agreement" value={agreement.agrees_with_backend ? 'Agree' : 'Disagree'} />
      {agreement.differences?.length ? (
        <ul className="ai-insights-risk-list">
          {agreement.differences.map((item, index) => (
            <li key={`${item?.field || item}-${index}`}>{item?.summary || item}</li>
          ))}
        </ul>
      ) : (
        <p className="ai-insights-card-copy">No differences were reported.</p>
      )}
    </SectionCard>
  )
}

export function RiskAssessmentCard({ analysis }) {
  const independent = independentAssessment(analysis)
  const risk = independent?.llm_risk_assessment || analysis.risk_assessment || {}
  return (
    <SectionCard eyebrow="Hard constraints applied" title="Risk Assessment">
      <div className="ai-insights-decision-grid">
        <Metric label="Risk Level" value={formatAnalysisEnumLabel(risk.risk_level)} />
        {risk.risk_off !== undefined ? <Metric label="Risk Off" value={risk.risk_off ? 'Yes' : 'No'} /> : null}
        {risk.allow_new_long !== undefined ? <Metric label="Allow New Long" value={risk.allow_new_long ? 'Yes' : 'No'} /> : null}
      </div>
      <p className="ai-insights-card-copy">{risk.summary || 'No risk summary was provided.'}</p>
    </SectionCard>
  )
}

export function SupportingEvidenceCard({ analysis }) {
  const evidence = independentAssessment(analysis)?.supporting_evidence || analysis.supporting_evidence || []
  return (
    <SectionCard eyebrow="Validated context" title="Supporting Evidence">
      {evidence.length ? (
        <div className="ai-insights-list-block">
          {evidence.map((item, index) => (
            <div className="ai-insights-context-line" key={`${item.factor}-${index}`}>
              <span>{item.factor}</span>
              <p><strong>{String(item.value)}</strong><small>{item.interpretation}</small></p>
            </div>
          ))}
        </div>
      ) : <p className="ai-insights-card-copy">No supporting evidence was returned.</p>}
    </SectionCard>
  )
}

export function LimitationsCard({ analysis }) {
  const limitations = independentAssessment(analysis)?.limitations || analysis.limitations || []
  return (
    <SectionCard eyebrow="Uncertainty" title="Limitations">
      {limitations.length ? (
        <ul className="ai-insights-risk-list">
          {limitations.map((item) => <li key={item}>{item}</li>)}
        </ul>
      ) : <p className="ai-insights-card-copy">No additional limitations were reported.</p>}
    </SectionCard>
  )
}

export function ValidatedSystemDecisionCard({ analysis }) {
  const decision = analysis.validated_system_decision || {}
  const agreement = analysis.quantitative_agreement || {}
  return (
    <SectionCard eyebrow="Django validated" title="Validated System Decision">
      <div className="ai-insights-decision-grid">
        <Metric label="Final Validated Strategy" value={strategyDisplayName(analysis, decision.validated_final_strategy)} />
        <Metric label="Backend / AI Agreement" value={agreement.agrees_with_backend === true ? 'Agree' : agreement.agrees_with_backend === false ? 'Disagree' : 'Unavailable'} />
        <Metric label="Hard Constraint Override" value={decision.hard_constraint_override_applied ? 'Applied' : 'Not Applied'} />
        <Metric label="Decision Source" value={formatAnalysisEnumLabel(decision.decision_source || analysis.decision_source)} />
        <Metric label="Fallback" value={decision.fallback_used ? 'Yes' : 'No'} />
      </div>
      {decision.override_reason ? <p className="ai-insights-card-copy">{decision.override_reason}</p> : null}
      {decision.llm_selected_strategy ? (
        <Metric label="Original AI Selection" value={strategyDisplayName(analysis, decision.llm_selected_strategy)} />
      ) : null}
    </SectionCard>
  )
}

export function AnalysisSourceCard({ analysis, metadata }) {
  const source = analysis.decision_source || metadata?.decision_source || 'llm_synthesis'
  const status = analysis.analysis_status || metadata?.analysis_status || 'success'
  const fallbackReason = analysis.fallback_reason || metadata?.fallback_reason
  return (
    <SectionCard eyebrow="Provenance" title="Analysis Source">
      <Metric label="Decision Source" value={formatAnalysisEnumLabel(source)} />
      <Metric label="Analysis Status" value={formatAnalysisEnumLabel(status)} />
      {fallbackReason ? <Metric label="Fallback Reason" value={formatAnalysisEnumLabel(fallbackReason)} /> : null}
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
  const generatedAt = formatGeneratedAt(metadata?.generated_at)
  return (
    <footer className="ai-insights-metadata">
      <span>
        {metadata?.is_restored ? 'Previous analysis' : 'Analysis'} · As of {metadata?.as_of_date || '—'} · Generated {generatedAt || '—'} · {metadata?.provider === 'deepseek' ? 'DeepSeek' : metadata?.provider || '—'} · {metadata?.analysis_version || '—'}
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
  const [isHistoryLoading, setIsHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const requestIdRef = useRef(0)
  const historyRequestIdRef = useRef(0)

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
    historyRequestIdRef.current += 1
    setIsLoading(true)
    setAnalysisUnavailable('')
    setError('')
    setHistoryError('')

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
        setAnalysis({
          ...response.analysis,
          symbol,
          metadata: {
            as_of_date: response.metadata?.as_of_date,
            analysis_version: response.metadata?.analysis_version,
            provider: response.metadata?.provider,
            model: response.metadata?.model,
            generated_at: response.generated_at,
            analysis_status: response.analysis_status,
            decision_source: response.decision_source,
            fallback_reason: response.fallback_reason,
            is_restored: false,
          },
        })
      })
      .catch((error) => {
        if (requestIdRef.current !== requestId || symbol !== selectedSymbol) return
        setError(getErrorMessage(error))
      })
      .finally(() => {
        if (requestIdRef.current === requestId) setIsLoading(false)
      })
  }

  useEffect(() => {
    const symbol = selectedSymbol
    if (!symbol) return undefined

    const requestId = historyRequestIdRef.current + 1
    historyRequestIdRef.current = requestId
    setIsHistoryLoading(true)
    setHistoryError('')

    agentAnalysisApi.latest({ symbol })
      .then((response) => {
        if (historyRequestIdRef.current !== requestId || symbol !== selectedSymbol) return
        if (response?.available && response.analysis) {
          setAnalysis({
            ...response.analysis,
            symbol: response.symbol || symbol,
            metadata: {
              as_of_date: response.as_of_date,
              analysis_version: response.analysis_version,
              provider: response.provider,
              model: response.model,
              generated_at: response.generated_at,
              analysis_status: response.analysis?.analysis_status,
              decision_source: response.analysis?.decision_source,
              fallback_reason: response.analysis?.fallback_reason,
              is_restored: true,
            },
          })
          setAnalysisUnavailable('')
          setError('')
        } else {
          setAnalysis(null)
          setAnalysisUnavailable('')
          setError('')
        }
      })
      .catch((error) => {
        if (historyRequestIdRef.current !== requestId || symbol !== selectedSymbol) return
        setAnalysis(null)
        setHistoryError(error?.message || 'Unable to load previous analysis.')
      })
      .finally(() => {
        if (historyRequestIdRef.current === requestId) setIsHistoryLoading(false)
      })

    return undefined
  }, [selectedSymbol])

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

      <section className="ai-insights-searchbar" aria-label="AI Insights security selection">
        <label className="ai-insights-searchbar-control">
          <span>Security</span>
          <SecuritySearchSelect
            id="ai-insights-asset"
            localSecurities={securities}
            selectedSecurity={selectedAsset}
            onSelect={selectAsset}
            disabled={isSecuritiesLoading || isLoading || isResolvingAsset}
            clearSelectionOnEdit={false}
          />
        </label>
        <div className="ai-insights-searchbar-selection" aria-live="polite">
          {selectedAsset ? (
            <strong>{selectedAsset.symbol} · {selectedAsset.name} · {selectedAsset.type}</strong>
          ) : (
            <span>No security selected</span>
          )}
        </div>
        <button
          className="ai-insights-generate-button"
          type="button"
          disabled={!selectedSymbol || isLoading || isSecuritiesLoading || isResolvingAsset}
          onClick={generateAnalysis}
        >
          {isLoading ? 'Analyzing...' : analysis ? 'Regenerate Analysis' : 'Generate AI Analysis'}
        </button>
      </section>
      {securitiesError && <p className="ai-insights-config-error" role="alert">{securitiesError}</p>}

      {isHistoryLoading && !analysis ? (
        <p className="ai-insights-history-status">Loading previous analysis...</p>
      ) : null}
      {historyError && !analysis ? (
        <p className="ai-insights-history-error" role="alert">{historyError}</p>
      ) : null}

      <div className="ai-insights-result-region">
        {isLoading ? (
          <LoadingState />
        ) : analysis ? (
          <>
            {analysisUnavailable ? <UnavailableState reason={analysisUnavailable} /> : null}
            {error ? <ErrorState message={error} /> : null}
            {analysis.backend_quantitative_assessment ? (
              <>
                <QuantitativeAssessmentCard analysis={analysis} />
                {analysis.llm_independent_assessment ? (
                  <>
                    <FinalAIAssessmentCard analysis={analysis} />
                    <FinalStrategyAssessmentCard analysis={analysis} />
                    <StrategyComparisonCard analysis={analysis} />
                    <div className="ai-insights-analysis-grid">
                      <RiskAssessmentCard analysis={analysis} />
                      <SupportingEvidenceCard analysis={analysis} />
                      <LimitationsCard analysis={analysis} />
                    </div>
                  </>
                ) : null}
                <ValidatedSystemDecisionCard analysis={analysis} />
                <div className="ai-insights-analysis-grid">
                  <QuantitativeAgreementCard analysis={analysis} />
                  <AnalysisSourceCard analysis={analysis} metadata={analysis.metadata} />
                </div>
              </>
            ) : analysis.final_market_assessment ? (
              <>
                <FinalAIAssessmentCard analysis={analysis} />
                <FinalStrategyAssessmentCard analysis={analysis} />
                <StrategyComparisonCard analysis={analysis} />
                <div className="ai-insights-analysis-grid">
                  <QuantitativeAssessmentCard analysis={analysis} />
                  <QuantitativeAgreementCard analysis={analysis} />
                  <RiskAssessmentCard analysis={analysis} />
                  <SupportingEvidenceCard analysis={analysis} />
                  <LimitationsCard analysis={analysis} />
                  <AnalysisSourceCard analysis={analysis} metadata={analysis.metadata} />
                </div>
              </>
            ) : (
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
              </>
            )}
            <MetadataFooter metadata={analysis.metadata} />
            <aside className="ai-insights-disclaimer" aria-label="AI analysis risk disclosure">
              <Icon name="shield" />
              <span>AI-generated decision support based on available system data. Historical performance does not guarantee future results.</span>
            </aside>
          </>
        ) : analysisUnavailable ? (
          <UnavailableState reason={analysisUnavailable} />
        ) : error ? (
          <ErrorState message={error} />
        ) : (
          <EmptyState symbol={selectedSymbol} />
        )}
      </div>
    </main>
  )
}
