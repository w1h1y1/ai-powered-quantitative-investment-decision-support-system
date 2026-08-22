import assert from 'node:assert/strict'
import test from 'node:test'
import {
  formatAnalysisEnumLabel,
  formatGeneratedAt,
  formatPercentValue,
  formatRatioAsPercent,
} from './aiInsightsFormatting.js'

test('formats market enums into human-readable labels', () => {
  assert.equal(formatAnalysisEnumLabel('high_volatility'), 'High Volatility')
  assert.equal(formatAnalysisEnumLabel('sideways_range'), 'Sideways Range')
  assert.equal(formatAnalysisEnumLabel('bullish_trend'), 'Bullish Trend')
  assert.equal(formatAnalysisEnumLabel('no_strategy'), 'No Active Strategy Signal')
  assert.equal(formatAnalysisEnumLabel('portfolio_unavailable'), 'Portfolio Unavailable')
})

test('formats ratios and percentage values separately', () => {
  assert.equal(formatRatioAsPercent(0.236591), '23.66%')
  assert.equal(formatPercentValue(66.6667), '66.67%')
  assert.equal(formatRatioAsPercent(null), 'N/A')
})

test('formats generated_at into a readable local timestamp', () => {
  assert.equal(formatGeneratedAt('2026-08-20T10:35:00'), '20 Aug 2026, 10:35')
  assert.equal(formatGeneratedAt(''), '')
  assert.equal(formatGeneratedAt('not-a-date'), '')
})
