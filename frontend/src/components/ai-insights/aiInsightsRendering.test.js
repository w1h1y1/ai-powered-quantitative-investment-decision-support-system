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
