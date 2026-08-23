import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

let vite
let components

before(async () => {
  vite = await createServer({ appType: 'custom', server: { hmr: false, middlewareMode: true } })
  components = await vite.ssrLoadModule(
    '/src/components/ai-insights/AIInsightsContent.jsx',
  )
})

after(async () => {
  await vite?.close()
})

function render(Component, props = {}) {
  const html = renderToStaticMarkup(React.createElement(Component, props))
  return html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
}

const analysis = {
  symbol: 'AAPL',
  metadata: {
    provider: 'deepseek',
    model: 'deepseek-chat',
    as_of_date: '2026-08-14',
    analysis_version: 'agent_analysis_v1',
  },
  market_view: { regime: 'high_volatility', direction: 'Mixed', summary: 'Elevated volatility.' },
  technical_view: { trend: 'Mixed', momentum: 'Weak', volatility: 'Elevated' },
  market_context_view: {
    broad_market: 'SPY sideways_range.',
    sector: 'XLK sideways_range.',
    confirmation: 'Neutral',
    confirmation_score: 0.5,
    confirmation_level: 'Neutral',
  },
  portfolio_view: {
    has_position: true,
    portfolio_weight: 0.2372,
    exposure_comment: 'AAPL is an existing position.',
  },
  backtest_view: {
    available: true,
    summary: 'Positive historical return.',
    strengths: ['Positive return'],
    risks: ['Historical drawdown'],
  },
  overall_assessment: 'Elevated volatility dominates.',
  risk_factors: ['High volatility', 'Weak momentum'],
}

const hybridAnalysis = {
  symbol: 'AAPL',
  metadata: {
    provider: 'deepseek',
    analysis_version: 'investment_agent_analysis_v3',
    analysis_status: 'success',
    decision_source: 'llm_synthesis',
  },
  analysis_status: 'success',
  decision_source: 'llm_synthesis',
  fallback_reason: null,
  final_market_assessment: {
    regime: 'sideways_range', direction: 'neutral', confidence: 0.78,
    summary: 'Weak trend strength supports a range-bound assessment.',
  },
  final_strategy_assessment: {
    selected_strategy: 'mean_reversion', confidence: 0.74, suitability: 'high',
    reason: 'Mean reversion better fits the supplied evidence.',
    why_not_alternatives: [
      'Trend Following has weaker support.',
      'Defensive / Risk-Off is not required.',
      'No Suitable Strategy is unnecessary.',
    ],
  },
  available_strategies: [
    { id: 'trend_following', name: 'Trend Following' },
    { id: 'mean_reversion', name: 'Mean Reversion' },
    { id: 'risk_off', name: 'Defensive / Risk-Off' },
    { id: 'no_strategy', name: 'No Suitable Strategy' },
  ],
  strategy_comparison: {
    trend_following: {
      suitability: 'low', supporting_factors: [],
      conflicting_factors: [{
        factor: 'ADX', value: 18.4,
        interpretation: 'Weak trend strength conflicts with the candidate.',
      }],
    },
    mean_reversion: {
      suitability: 'high', supporting_factors: [{
        factor: 'ADX', value: 18.4,
        interpretation: 'Weak trend strength supports range-oriented evaluation.',
      }],
      conflicting_factors: [],
    },
    risk_off: { suitability: 'low', supporting_factors: [], conflicting_factors: [] },
    no_strategy: { suitability: 'low', supporting_factors: [], conflicting_factors: [] },
  },
  backtest_evidence_available: false,
  quantitative_assessment: {
    preliminary_regime: 'bullish_trend', suggested_strategy: 'trend_following',
    confidence: 0.72, risk_off: false, allow_new_long: true,
    explanation: ['The deterministic engine detected a positive trend.'],
  },
  quantitative_agreement: {
    agrees_with_backend: false,
    differences: ['Final regime is sideways rather than bullish.'],
  },
  risk_assessment: {
    risk_level: 'medium', risk_off: false, allow_new_long: true,
    summary: 'Risk remains moderate.',
  },
  supporting_evidence: [{
    factor: 'ADX', value: 18.4,
    interpretation: 'Weak trend strength supports a range assessment.',
  }],
  limitations: ['Strategy-specific comparison backtests are unavailable.'],
}

const dualAnalysis = {
  analysis_version: 'investment_agent_analysis_v4',
  analysis_status: 'success',
  decision_source: 'llm_synthesis_with_constraint_override',
  llm_assessment_mode: 'independent',
  backend_suggestion_exposed_to_llm: false,
  hybrid_backtest_evidence: {
    available: true,
    strategy: 'market-regime-core-swing',
    strategy_label: 'Market-Regime Hybrid Strategy (Core + Swing)',
    symbol: 'AAPL',
    evidence_scope: 'complete_hybrid_strategy',
    comparison_supported: false,
    start_date: '2025-08-14',
    end_date: '2026-08-14',
    total_return: 12.407411,
    max_drawdown: 8.307625,
    annualized_volatility: 12.418187,
    win_rate: 66.666667,
    trade_count: 36,
    transaction_fee: 1,
    total_fees: 36,
  },
  available_strategies: hybridAnalysis.available_strategies,
  backend_quantitative_assessment: hybridAnalysis.quantitative_assessment,
  llm_independent_assessment: {
    llm_market_assessment: hybridAnalysis.final_market_assessment,
    llm_strategy_comparison: hybridAnalysis.strategy_comparison,
    llm_final_strategy_assessment: hybridAnalysis.final_strategy_assessment,
    llm_risk_assessment: { risk_level: 'medium', summary: 'Independent risk review.' },
    backtest_evidence_available: false,
    supporting_evidence: hybridAnalysis.supporting_evidence,
    limitations: hybridAnalysis.limitations,
  },
  quantitative_agreement: {
    agrees_with_backend: false,
    regime_agreement: false,
    strategy_agreement: false,
    differences: [{
      field: 'selected_strategy',
      summary: 'The deterministic and independent strategy selections differ.',
    }],
  },
  validated_system_decision: {
    backend_preliminary_strategy: 'trend_following',
    llm_selected_strategy: 'mean_reversion',
    validated_final_strategy: 'risk_off',
    hard_constraint_override_applied: true,
    override_reason: 'New long exposure is prohibited by the deterministic risk engine.',
    decision_source: 'llm_synthesis_with_constraint_override',
    fallback_used: false,
    backend_hard_constraints: { risk_off: true, allow_new_long: false },
    recommended_action: {
      action: 'reduce_risk',
      label: 'Reduce Risk / No New Long',
      summary: 'Review the existing position for risk reduction under the active Risk-Off constraint.',
      position_context: 'existing_position',
      new_entry_allowed: false,
      suggested_exposure_change: 'review_risk_reduction',
      automatic_execution: false,
      monitoring_triggers: [{
        factor: 'Risk-Off constraint',
        condition: 'A hard risk constraint prohibits new long exposure.',
      }],
      reassessment_reason: 'Regenerate the analysis when a hard risk constraint changes.',
    },
  },
}

test('empty state no longer exposes rule-based mock UI', () => {
  const text = render(components.EmptyState)
  assert.match(text, /No AI analysis generated yet/)
  assert.doesNotMatch(text, /Rule-based mock|Demo Analysis|No rule-based insight/)
})

test('overview renders Django-controlled market facts', () => {
  const text = render(components.OverviewCard, { analysis, metadata: analysis.metadata })
  assert.match(text, /High Volatility/)
  assert.match(text, /Mixed/)
  assert.match(text, /Neutral/)
  assert.match(text, /2026-08-14/)
})

test('decision summary renders structured decision fields', () => {
  const text = render(components.DecisionSummaryCard, {
    analysis: {
      ...analysis,
      decision_summary: {
        stance: 'Cautious',
        confidence: 'Medium',
        suggested_approach: 'Wait for Confirmation',
        suitable_strategy: 'Reduced Exposure / Wait',
        time_horizon: 'Short Term',
        key_reasons: ['High volatility', 'Weak momentum'],
        main_risk: 'High volatility',
      },
    },
  })

  assert.match(text, /AI Decision Summary/)
  assert.match(text, /Cautious/)
  assert.match(text, /Reduced Exposure \/ Wait/)
  assert.match(text, /Key Reasons/)
  assert.match(text, /Main Risk/)
})

test('analysis cards render required sections', () => {
  assert.match(render(components.MarketViewCard, { analysis }), /Market View/)
  assert.match(render(components.TechnicalViewCard, { analysis }), /Technical Analysis/)
  assert.match(render(components.MarketContextCard, { analysis }), /Market Context/)
  assert.match(render(components.PortfolioContextCard, { analysis }), /Portfolio Context/)
  assert.match(render(components.BacktestEvidenceCard, { analysis }), /Historical Backtest Evidence/)
  assert.match(render(components.OverallAssessmentCard, { analysis }), /Overall Assessment/)
  assert.match(render(components.RiskFactorsCard, { analysis }), /Risk Factors/)
})

test('market context does not duplicate confirmation blocks', () => {
  const text = render(components.MarketContextCard, { analysis })
  assert.match(text, /Confirmation Neutral Score 0.5/)
  assert.doesNotMatch(text, /Confirmation Level/)
  assert.doesNotMatch(text, /Confirmation Score/)
})

test('portfolio weight is rendered as a user-readable percentage', () => {
  const text = render(components.PortfolioContextCard, { analysis })
  assert.match(text, /Portfolio Weight 23.72%/)
})

test('no-position portfolio renders as no current position, not an error', () => {
  const text = render(components.PortfolioContextCard, {
    analysis: {
      ...analysis,
      portfolio_view: { has_position: false, portfolio_weight: 0, exposure_comment: 'No JPM position.' },
    },
  })
  assert.match(text, /No current position/)
  assert.doesNotMatch(text, /role="alert"/)
})

test('unavailable backtest renders an explicit unavailable state', () => {
  const text = render(components.BacktestEvidenceCard, {
    analysis: {
      ...analysis,
      backtest_view: { available: false, summary: '', strengths: [], risks: [] },
    },
  })
  assert.match(text, /Backtest evidence unavailable/)
})

test('analysis unavailable and error states are explicit', () => {
  assert.match(render(components.UnavailableState, { reason: 'LLM service is not configured.' }), /AI analysis is currently unavailable/)
  assert.match(render(components.ErrorState, { message: 'Please try again.' }), /Unable to generate AI analysis/)
})

test('metadata footer shows generated timestamp and restored marker', () => {
  const text = render(components.MetadataFooter, {
    metadata: {
      generated_at: '2026-08-20T10:35:00',
      as_of_date: '2026-08-18',
      provider: 'deepseek',
      analysis_version: 'agent_analysis_v1',
      is_restored: true,
    },
  })
  assert.match(text, /Previous analysis/)
  assert.match(text, /As of 2026-08-18/)
  assert.match(text, /Generated 20 Aug 2026/)
  assert.match(text, /DeepSeek/)
})

test('metadata footer labels freshly generated analysis without the restored marker', () => {
  const text = render(components.MetadataFooter, {
    metadata: {
      generated_at: '2026-08-20T10:35:00',
      as_of_date: '2026-08-18',
      analysis_version: 'agent_analysis_v1',
      is_restored: false,
    },
  })
  assert.match(text, /Analysis · As of 2026-08-18/)
  assert.doesNotMatch(text, /Previous analysis/)
})

test('rendered analysis contains no trading recommendation language', () => {
  const text = render(components.OverallAssessmentCard, { analysis })
  assert.doesNotMatch(text, /\bBUY\b|\bSELL\b|\bHOLD\b|Target Price|Position Size/i)
})

test('hybrid decision cards distinguish final and preliminary assessments', () => {
  const finalText = render(components.FinalAIAssessmentCard, { analysis: hybridAnalysis })
  const strategyText = render(components.FinalStrategyAssessmentCard, { analysis: hybridAnalysis })
  const quantitativeText = render(components.QuantitativeAssessmentCard, { analysis: hybridAnalysis })
  const agreementText = render(components.QuantitativeAgreementCard, { analysis: hybridAnalysis })

  assert.match(finalText, /Independent AI Assessment/)
  assert.match(finalText, /Sideways Range/)
  assert.match(strategyText, /Mean Reversion/)
  assert.match(strategyText, /Confidence 74.00%/)
  assert.match(strategyText, /Why Not the Alternatives/)
  assert.match(quantitativeText, /Bullish Trend/)
  assert.match(quantitativeText, /Trend Following/)
  assert.match(agreementText, /Disagree/)
  assert.match(agreementText, /Final regime is sideways rather than bullish/)
})

test('v4 renders backend, independent AI, and validated system decision separately', () => {
  const backendText = render(components.QuantitativeAssessmentCard, { analysis: dualAnalysis })
  const aiText = render(components.FinalAIAssessmentCard, { analysis: dualAnalysis })
  const decisionText = render(components.ValidatedSystemDecisionCard, { analysis: dualAnalysis })

  assert.match(backendText, /Quantitative Engine Assessment/)
  assert.match(backendText, /Trend Following/)
  assert.match(aiText, /Independent AI Assessment/)
  assert.match(aiText, /generated independently without receiving the backend’s suggested strategy/)
  assert.match(decisionText, /Final Validated Decision/)
  assert.match(decisionText, /Final Validated Strategy Defensive \/ Risk-Off/)
  assert.match(decisionText, /Original AI Selection Mean Reversion/)
  assert.match(decisionText, /Hard Constraint Override Applied/)
})

test('independence badge is hidden unless backend suggestion exposure is explicitly false', () => {
  const exposed = { ...dualAnalysis, backend_suggestion_exposed_to_llm: true }
  const text = render(components.FinalAIAssessmentCard, { analysis: exposed })
  assert.doesNotMatch(text, /generated independently without receiving/)
})

test('v4 fallback renders backend and system result without claiming AI success', () => {
  const fallback = {
    ...dualAnalysis,
    analysis_status: 'fallback',
    decision_source: 'quantitative_fallback',
    llm_assessment_mode: 'unavailable',
    llm_independent_assessment: null,
    validated_system_decision: {
      ...dualAnalysis.validated_system_decision,
      llm_selected_strategy: null,
      validated_final_strategy: 'trend_following',
      hard_constraint_override_applied: false,
      decision_source: 'quantitative_fallback',
      fallback_used: true,
    },
  }
  const text = render(components.ValidatedSystemDecisionCard, { analysis: fallback })
  assert.match(text, /Fallback Yes/)
  assert.doesNotMatch(text, /Original AI Selection/)
})

test('strategy comparison renders every backend-named candidate and verified factors', () => {
  const text = render(components.StrategyComparisonCard, { analysis: hybridAnalysis })
  assert.match(text, /Strategy Comparison/)
  assert.match(text, /Current Market Suitability Comparison/)
  assert.doesNotMatch(text, /Comparable Backtest Evidence|Unavailable/)
  assert.match(text, /Trend Following/)
  assert.match(text, /Mean Reversion/)
  assert.match(text, /Defensive \/ Risk-Off/)
  assert.match(text, /No Active Strategy Signal/)
  assert.match(text, /ADX 18.4/)
  assert.match(text, /Supporting Factors/)
  assert.match(text, /Conflicting Factors/)
})

test('hybrid backtest card renders only real whole-strategy metrics and scope', () => {
  const text = render(components.HybridBacktestEvidenceCard, { analysis: dualAnalysis })
  assert.match(text, /Hybrid Strategy Backtest Evidence/)
  assert.match(text, /Available/)
  assert.match(text, /Market-Regime Hybrid Strategy \(Core \+ Swing\)/)
  assert.match(text, /Total Return 12\.41%/)
  assert.match(text, /Maximum Drawdown 8\.31%/)
  assert.match(text, /Executed Orders 36/)
  assert.match(text, /does not compare standalone trend-following and mean-reversion strategies/)
  assert.doesNotMatch(text, /Sharpe|Annualized Return|CAGR|Alpha/)
})

test('hybrid backtest unavailable path is compact, specific, and explains assessment basis', () => {
  const unavailable = {
    ...dualAnalysis,
    hybrid_backtest_evidence: {
      available: false,
      strategy: 'market-regime-core-swing',
      symbol: 'AAPL',
      unavailable_reason: 'The Hybrid Strategy backtest result was incomplete.',
    },
  }
  const text = render(components.HybridBacktestEvidenceCard, { analysis: unavailable })
  assert.match(text, /Not available for this analysis/)
  assert.match(text, /backtest result was incomplete/)
  assert.match(text, /technical indicators, market regime, relative performance, entry conditions, and risk constraints/)
  assert.doesNotMatch(text, /^Unavailable$/)
})

test('hybrid backtest card remains optional for older stored analyses', () => {
  assert.equal(components.HybridBacktestEvidenceCard({ analysis: {} }), null)
})

test('strategy comparison remains optional for stored v2 analyses', () => {
  assert.equal(components.StrategyComparisonCard({ analysis: {} }), null)
})

test('hybrid decision cards render evidence, risk, limitations, and source', () => {
  assert.match(render(components.RiskAssessmentCard, { analysis: hybridAnalysis }), /Risk Assessment/)
  assert.match(render(components.SupportingEvidenceCard, { analysis: hybridAnalysis }), /ADX 18.4/)
  assert.match(render(components.LimitationsCard, { analysis: hybridAnalysis }), /comparison backtests are unavailable/)
  assert.match(render(components.AnalysisSourceCard, {
    analysis: hybridAnalysis,
    metadata: hybridAnalysis.metadata,
  }), /Llm Synthesis|llm_synthesis/i)
})

test('fallback source is explicit and optional hybrid fields do not crash', () => {
  const fallback = {
    ...hybridAnalysis,
    analysis_status: 'fallback',
    decision_source: 'quantitative_fallback',
    fallback_reason: 'llm_invalid_json',
    supporting_evidence: undefined,
    limitations: undefined,
  }
  const sourceText = render(components.AnalysisSourceCard, { analysis: fallback })
  assert.match(sourceText, /Quantitative Fallback|quantitative_fallback/i)
  assert.match(sourceText, /Fallback/)
  assert.match(render(components.SupportingEvidenceCard, { analysis: fallback }), /No supporting evidence/)
  assert.match(render(components.LimitationsCard, { analysis: fallback }), /No additional limitations/)
})

test('recommended action is explicit and never claims automatic execution', () => {
  const text = render(components.RecommendedActionCard, { analysis: dualAnalysis })
  assert.match(text, /Recommended Action/)
  assert.match(text, /Reduce Risk \/ No New Long/)
  assert.match(text, /New Entry Allowed No/)
  assert.match(text, /Automatic Execution No/)
  assert.match(text, /No order will be placed automatically/)
})

test('no-strategy action differs correctly for no position and existing position', () => {
  const decision = dualAnalysis.validated_system_decision
  const noPosition = {
    ...dualAnalysis,
    validated_system_decision: {
      ...decision,
      validated_final_strategy: 'no_strategy',
      recommended_action: {
        ...decision.recommended_action,
        action: 'wait',
        label: 'Wait / No New Entry',
        position_context: 'no_position',
        summary: 'No active strategy currently meets its entry requirements.',
      },
    },
  }
  const existingPosition = {
    ...noPosition,
    validated_system_decision: {
      ...noPosition.validated_system_decision,
      recommended_action: {
        ...noPosition.validated_system_decision.recommended_action,
        action: 'hold_and_monitor',
        label: 'Hold and Monitor',
        position_context: 'existing_position',
      },
    },
  }
  const waitText = render(components.RecommendedActionCard, { analysis: noPosition })
  const holdText = render(components.RecommendedActionCard, { analysis: existingPosition })
  assert.match(waitText, /Wait \/ No New Entry/)
  assert.doesNotMatch(waitText, /Hold and Monitor/)
  assert.match(holdText, /Hold and Monitor/)
})

test('no strategy is explained as active abstention rather than failure', () => {
  const noStrategy = {
    ...dualAnalysis,
    validated_system_decision: {
      ...dualAnalysis.validated_system_decision,
      validated_final_strategy: 'no_strategy',
      hard_constraint_override_applied: false,
      override_reason: null,
    },
  }
  const text = render(components.ValidatedSystemDecisionCard, { analysis: noStrategy })
  assert.match(text, /No Active Strategy Signal/)
  assert.match(text, /active abstention after strategy comparison, not a system failure/)
})

const expandedEvidenceAnalysis = {
  ...dualAnalysis,
  llm_independent_assessment: {
    ...dualAnalysis.llm_independent_assessment,
    supporting_evidence: [
      { factor: 'Latest Price', source_path: 'market_data.latest.close', value: 214.3764, interpretation: 'Latest supplied close.' },
      { factor: 'MA20', source_path: 'technical_analysis.moving_averages.ma20', value: 211.2349, interpretation: 'Short moving average.' },
      { factor: 'MA60', source_path: 'technical_analysis.moving_averages.ma60', value: 207.9876, interpretation: 'Medium moving average.' },
      { factor: 'RSI14', source_path: 'technical_analysis.momentum.rsi14', value: 48.376, interpretation: 'Momentum reading.' },
      { factor: 'MACD', source_path: 'technical_analysis.momentum.macd', value: -0.107332, interpretation: 'Momentum spread.' },
      { factor: 'ADX', source_path: 'technical_analysis.trend.adx', value: 18.4000005, interpretation: 'Trend strength.' },
      { factor: 'Choppiness', source_path: 'technical_analysis.trend.choppiness', value: 63.1234, interpretation: 'Range tendency.' },
      { factor: 'Volatility Percentile', source_path: 'market_regime.volatility.volatility_percentile', value: 0.843254, interpretation: 'Relative volatility.' },
      { factor: 'Relative to SPY 20D', source_path: 'technical_analysis.relative_performance.vs_spy_20d', value: 0.024676, interpretation: 'Benchmark-relative return.' },
      { factor: 'Mean Reversion Entry Conditions Met', source_path: 'technical_analysis.mean_reversion_entry.entry_conditions_met', value: false, interpretation: 'Configured entry gate.' },
    ],
    limitations: ['One', 'Two', 'Three', 'Four', 'Five'],
  },
}

test('key evidence defaults to seven relevant rows and offers expansion', () => {
  const selected = components.selectKeyEvidence(expandedEvidenceAnalysis)
  const text = render(components.SupportingEvidenceCard, { analysis: expandedEvidenceAnalysis })
  assert.equal(selected.length, 7)
  assert.match(text, /Show all evidence \(10\)/)
  assert.doesNotMatch(text, /Relative to SPY 20D/)
})

test('expanded evidence is grouped and exposes Show less', () => {
  const text = render(components.SupportingEvidenceCard, {
    analysis: expandedEvidenceAnalysis,
    initiallyExpanded: true,
  })
  assert.match(text, /Price and Moving Averages/)
  assert.match(text, /Momentum/)
  assert.match(text, /Trend and Market Regime/)
  assert.match(text, /Volatility and Risk/)
  assert.match(text, /Relative Performance/)
  assert.match(text, /Strategy Entry Conditions/)
  assert.match(text, /All Supporting Evidence/)
  assert.match(text, /Show less/)
})

test('evidence values use readable precision, percentages, and booleans', () => {
  const evidence = expandedEvidenceAnalysis.llm_independent_assessment.supporting_evidence
  assert.equal(components.formatEvidenceValue(evidence[0]), '214.38')
  assert.equal(components.formatEvidenceValue(evidence[7]), '84.33%')
  assert.equal(components.formatEvidenceValue(evidence[8]), '2.47%')
  assert.equal(components.formatEvidenceValue(evidence[9]), 'Not Met')
})

test('limitations default to three and expand without changing the source payload', () => {
  const collapsed = render(components.LimitationsCard, { analysis: expandedEvidenceAnalysis })
  const expanded = render(components.LimitationsCard, {
    analysis: expandedEvidenceAnalysis,
    initiallyExpanded: true,
  })
  assert.match(collapsed, /One Two Three/)
  assert.doesNotMatch(collapsed, /Four/)
  assert.match(collapsed, /Show all limitations \(5\)/)
  assert.match(expanded, /Four Five/)
  assert.match(expanded, /Show fewer limitations/)
})

test('recommended action remains optional for older stored responses', () => {
  assert.equal(components.RecommendedActionCard({ analysis: hybridAnalysis }), null)
})
