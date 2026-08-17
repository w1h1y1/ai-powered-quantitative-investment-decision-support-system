import assert from 'node:assert/strict'
import test from 'node:test'
import {
  formatAnalysisEnumLabel,
  formatPercentValue,
  formatRatioAsPercent,
} from './aiInsightsFormatting.js'

test('formats market enums into human-readable labels', () => {
  assert.equal(formatAnalysisEnumLabel('high_volatility'), 'High Volatility')
  assert.equal(formatAnalysisEnumLabel('sideways_range'), 'Sideways Range')
  assert.equal(formatAnalysisEnumLabel('bullish_trend'), 'Bullish Trend')
})

test('formats ratios and percentage values separately', () => {
  assert.equal(formatRatioAsPercent(0.236591), '23.66%')
  assert.equal(formatPercentValue(66.6667), '66.67%')
  assert.equal(formatRatioAsPercent(null), 'N/A')
})
