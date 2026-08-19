import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  DASHBOARD_SEARCH_MESSAGES,
  clearDashboardSearch,
  createDashboardSearchState,
  dashboardSearchStatus,
  failDashboardSearch,
  resolveDashboardSearch,
  startDashboardSearch,
  updateDashboardSearchQuery,
} from './dashboardSearchModel.js'

const aapl = {
  id: 1,
  symbol: 'AAPL',
  name: 'Apple Inc.',
  exchange: 'NASDAQ',
  mic_code: 'XNAS',
  instrument_type: 'Common Stock',
  currency: 'USD',
  is_local: true,
}

function remoteXom() {
  return {
    id: null,
    symbol: 'XOM',
    name: 'Exxon Mobil Corporation',
    exchange: 'NYSE',
    mic_code: 'XNYS',
    instrument_type: 'Common Stock',
    currency: 'USD',
    is_local: false,
    source: 'remote',
  }
}

test('Given AAPL selected, When the user types XOM into the search box, Then only the query changes and no selection state exists in the search slice', () => {
  const state = createDashboardSearchState({ query: '', results: [], isSearching: false, hasSearched: false, error: '' })

  const next = updateDashboardSearchQuery(state, 'XOM')

  assert.equal(next.query, 'XOM')
  assert.equal('selectedSecurity' in next, false)
  assert.equal('selectedSecurityId' in next, false)
  assert.deepEqual(next.results, [])
  assert.equal(next.hasSearched, false)
})

test('Given an existing search with results, When the user edits the query, Then stale results and the previous error are cleared', () => {
  const state = createDashboardSearchState({
    query: 'JPM',
    results: [{ symbol: 'JPM' }],
    hasSearched: true,
    error: 'old error',
  })

  const next = updateDashboardSearchQuery(state, 'QQQ')

  assert.equal(next.query, 'QQQ')
  assert.deepEqual(next.results, [])
  assert.equal(next.hasSearched, false)
  assert.equal(next.error, '')
})

test('Given a remote XOM result from the API, When the search resolves, Then XOM is merged into the result list', () => {
  const state = createDashboardSearchState({ query: 'XOM' })
  const started = startDashboardSearch(state)

  const next = resolveDashboardSearch(started, { items: [remoteXom()] }, [aapl], 'XOM')

  assert.equal(next.isSearching, false)
  assert.equal(next.hasSearched, true)
  assert.equal(next.error, '')
  assert.deepEqual(next.results.map((item) => item.symbol), ['XOM'])
  assert.equal(next.results[0].is_local, false)
})

test('Given a search with no matches, Then the UI status shows the explicit no-result message', () => {
  const state = createDashboardSearchState({ query: 'ZZZZ' })
  const resolved = resolveDashboardSearch(startDashboardSearch(state), { items: [] }, [aapl], 'ZZZZ')

  assert.deepEqual(resolved.results, [])
  assert.equal(resolved.hasSearched, true)
  assert.deepEqual(dashboardSearchStatus(resolved), {
    kind: 'empty',
    message: DASHBOARD_SEARCH_MESSAGES.noResults,
  })
})

test('Given a search API failure, Then the error message is explicit and previous results are cleared', () => {
  const state = createDashboardSearchState({ query: 'XOM', results: [{ symbol: 'XOM' }] })

  const failed = failDashboardSearch(startDashboardSearch(state))

  assert.equal(failed.error, DASHBOARD_SEARCH_MESSAGES.failure)
  assert.deepEqual(failed.results, [])
  assert.equal(failed.hasSearched, true)
  assert.deepEqual(dashboardSearchStatus(failed), {
    kind: 'error',
    message: DASHBOARD_SEARCH_MESSAGES.failure,
  })
})

test('Given a selection has been made, When search is cleared, Then the search slice returns to its idle empty state', () => {
  const state = createDashboardSearchState({ query: 'XOM', results: [remoteXom()], hasSearched: true })

  assert.deepEqual(clearDashboardSearch(state), createDashboardSearchState())
})

test('The dashboard search control wires Enter and the Search button to the same onSearch handler and only updates the query while typing', () => {
  const source = readFileSync(new URL('./DashboardSecuritySearch.jsx', import.meta.url), 'utf8')

  assert.match(source, /onClick=\{onSearch\}/)
  assert.match(source, /event\.key === 'Enter'/)
  assert.match(source, /onSearch\(\)/)
  assert.match(source, /onChange=\{\(event\) => onQueryChange\(event\.target\.value\)\}/)
  assert.match(source, /'Search'/)
  assert.match(source, /DASHBOARD_SEARCH_MESSAGES\.searching/)
  assert.match(source, /dashboardSearchStatus\(/)
  assert.match(source, /status\.message/)
})

test('DashboardContent keeps search state separate from the selected security and preserves the stale-response guard', () => {
  const source = readFileSync(new URL('./DashboardContent.jsx', import.meta.url), 'utf8')

  assert.match(source, /const \[securitySearch, setSecuritySearch\]/)
  assert.match(source, /securityApi\.search\(query\)/)
  assert.match(source, /onSearch=\{runDashboardSearch\}/)
  assert.match(source, /onQueryChange=\{handleSecuritySearchQueryChange\}/)
  assert.match(source, /onSelect=\{selectSecuritySearchResult\}/)
  assert.match(source, /shouldApplyMarketDataResponse\(marketDataRequestIdRef\.current, requestId\)/)
  assert.match(source, /marketDataResponseMatchesRequest\(response, requestParams\)/)
})
