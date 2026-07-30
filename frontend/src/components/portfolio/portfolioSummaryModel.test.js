import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  SUMMARY_CARD_LABELS,
  SUMMARY_GRID_COLUMNS,
  buildPortfolioSummaryCards,
  normalizePortfolioSummary,
} from './portfolioSummaryModel.js'

function apiSummary(overrides = {}) {
  return {
    portfolio_id: 8,
    portfolio_name: 'My Portfolio',
    portfolio_created_at: '2026-07-25T08:00:00Z',
    base_currency: 'USD',
    price_source: 'DEMO_STATIC',
    holdings_count: 1,
    total_asset_value: '189.84',
    holdings_market_value: '189.84',
    remaining_liquidity: '0.00',
    total_cost: '300.00',
    unrealized_profit_loss: '-110.16',
    unrealized_return_percent: '-36.72',
    allocations: [],
    ...overrides,
  }
}

function cardValue(cards, label) {
  return cards.find((card) => card.label === label)?.value
}

test('uses API remaining_liquidity 0 as $0.00', () => {
  const portfolio = normalizePortfolioSummary(apiSummary({ remaining_liquidity: '0.00' }))
  const cards = buildPortfolioSummaryCards(portfolio.summary)

  assert.equal(cardValue(cards, 'Remaining Liquidity'), '$0.00')
})

test('uses API remaining_liquidity 10000 as $10,000.00', () => {
  const portfolio = normalizePortfolioSummary(apiSummary({
    remaining_liquidity: '10000.00',
    total_asset_value: '10189.84',
  }))
  const cards = buildPortfolioSummaryCards(portfolio.summary)

  assert.equal(cardValue(cards, 'Remaining Liquidity'), '$10,000.00')
  assert.equal(cardValue(cards, 'Total Assets'), '$10,189.84')
})

test('does not fallback missing remaining_liquidity to hardcoded or legacy values', () => {
  const portfolio = normalizePortfolioSummary(apiSummary({
    available_liquidity: '10000.00',
    remaining_liquidity: undefined,
  }))
  const cards = buildPortfolioSummaryCards(portfolio.summary)

  assert.equal(portfolio.summary.availableFunds, 0)
  assert.equal(cardValue(cards, 'Remaining Liquidity'), '$0.00')
})

test('keeps the six summary cards in the desktop 3x2 order', () => {
  const portfolio = normalizePortfolioSummary(apiSummary())
  const cards = buildPortfolioSummaryCards(portfolio.summary)

  assert.deepEqual(cards.map((card) => card.label), SUMMARY_CARD_LABELS)
  assert.deepEqual(cards.slice(0, 3).map((card) => card.label), [
    'Total Assets',
    'Holdings Market Value',
    'Remaining Liquidity',
  ])
  assert.deepEqual(cards.slice(3).map((card) => card.label), [
    'Total Cost',
    'Unrealized Profit / Loss',
    'Return Percentage',
  ])
  assert.equal(cards.length, 6)
  assert.equal(SUMMARY_GRID_COLUMNS.desktop, 3)
})

test('portfolio summary CSS defines 3 desktop, 2 tablet, and 1 mobile columns', () => {
  const css = readFileSync(new URL('../../styles/portfolio.css', import.meta.url), 'utf8')

  assert.match(css, /\.portfolio-summary-grid\s*{[^}]*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/)
  assert.match(css, /@media\s*\(max-width:\s*760px\)\s*{[\s\S]*?\.portfolio-summary-grid\s*{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/)
  assert.match(css, /@media\s*\(max-width:\s*520px\)\s*{[\s\S]*?\.portfolio-summary-grid\s*{[^}]*grid-template-columns:\s*1fr/)
})

test('summary card values update when the API summary changes', () => {
  const first = normalizePortfolioSummary(apiSummary({
    holdings_count: 1,
    total_asset_value: '189.84',
    holdings_market_value: '189.84',
    remaining_liquidity: '0.00',
    total_cost: '300.00',
    unrealized_profit_loss: '-110.16',
    unrealized_return_percent: '-36.72',
  }))
  const second = normalizePortfolioSummary(apiSummary({
    holdings_count: 2,
    total_asset_value: '11500.50',
    holdings_market_value: '1500.50',
    remaining_liquidity: '10000.00',
    total_cost: '1400.25',
    unrealized_profit_loss: '100.25',
    unrealized_return_percent: '7.16',
  }))

  const firstCards = buildPortfolioSummaryCards(first.summary)
  const secondCards = buildPortfolioSummaryCards(second.summary)

  assert.equal(cardValue(firstCards, 'Total Assets'), '$189.84')
  assert.equal(cardValue(secondCards, 'Total Assets'), '$11,500.50')
  assert.equal(cardValue(firstCards, 'Holdings Market Value'), '$189.84')
  assert.equal(cardValue(secondCards, 'Holdings Market Value'), '$1,500.50')
  assert.equal(cardValue(firstCards, 'Remaining Liquidity'), '$0.00')
  assert.equal(cardValue(secondCards, 'Remaining Liquidity'), '$10,000.00')
  assert.equal(cardValue(firstCards, 'Total Cost'), '$300.00')
  assert.equal(cardValue(secondCards, 'Total Cost'), '$1,400.25')
  assert.equal(cardValue(firstCards, 'Unrealized Profit / Loss'), '-$110.16')
  assert.equal(cardValue(secondCards, 'Unrealized Profit / Loss'), '+$100.25')
  assert.equal(cardValue(firstCards, 'Return Percentage'), '-36.72%')
  assert.equal(cardValue(secondCards, 'Return Percentage'), '7.16%')
})
