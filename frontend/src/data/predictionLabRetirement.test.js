import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { navigationItems, workspaceContent } from './mockData.js'
import {
  isKnownNavigationPath,
  resolveNavigationSection,
} from './navigationRouting.js'

const appSourcePath = fileURLToPath(new URL('../App.jsx', import.meta.url))
const mainSourcePath = fileURLToPath(new URL('../main.jsx', import.meta.url))

test('formal navigation and workspace metadata no longer expose Prediction Lab', () => {
  assert.deepEqual(
    navigationItems.map((item) => item.label),
    [
      'Dashboard',
      'Market Analysis',
      'Watchlist',
      'Portfolio',
      'Strategy Backtest',
      'AI Insights',
    ],
  )
  assert.equal(navigationItems.some((item) => item.id === 'prediction-lab'), false)
  assert.equal(Object.hasOwn(workspaceContent, 'prediction-lab'), false)
})

test('retired Prediction Lab URL is unknown and resolves to Dashboard', () => {
  assert.equal(isKnownNavigationPath('/prediction-lab', navigationItems), false)
  assert.equal(
    resolveNavigationSection('/prediction-lab', { section: 'prediction-lab' }, navigationItems),
    'dashboard',
  )
  assert.equal(isKnownNavigationPath('/backtest', navigationItems), true)
  assert.equal(resolveNavigationSection('/backtest', null, navigationItems), 'strategy-backtesting')
})

test('production entry files do not import the retired page or its stylesheet', async () => {
  const [appSource, mainSource] = await Promise.all([
    readFile(appSourcePath, 'utf8'),
    readFile(mainSourcePath, 'utf8'),
  ])

  assert.doesNotMatch(appSource, /PredictionLabPage|activeNavigationItem\.id === 'prediction-lab'/)
  assert.doesNotMatch(mainSource, /prediction-lab\.css/)
})
