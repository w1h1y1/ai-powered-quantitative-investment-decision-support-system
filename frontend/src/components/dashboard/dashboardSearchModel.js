import { mergeSecuritySearchOptions } from '../security/securitySearchModel.js'

export const DASHBOARD_SEARCH_MESSAGES = {
  searching: 'Searching...',
  noResults: 'No matching securities found.',
  failure: 'Unable to search securities. Please try again.',
}

/**
 * Search state is intentionally a separate slice from the selected-security
 * state: typing, searching, results, and errors must never change which
 * security the Dashboard is displaying. Only an explicit result selection
 * (or a Popular chip) updates the selected security.
 */
export function createDashboardSearchState(initial = {}) {
  return {
    query: '',
    results: [],
    isSearching: false,
    hasSearched: false,
    error: '',
    ...initial,
  }
}

export function updateDashboardSearchQuery(state, query) {
  return {
    ...state,
    query,
    results: [],
    hasSearched: false,
    error: '',
  }
}

export function startDashboardSearch(state) {
  return {
    ...state,
    isSearching: true,
    hasSearched: false,
    error: '',
  }
}

export function resolveDashboardSearch(state, payload, localSecurities, query) {
  const searchedQuery = String(query ?? state.query ?? '').trim()
  return {
    ...state,
    results: mergeSecuritySearchOptions(localSecurities, payload?.items, searchedQuery),
    isSearching: false,
    hasSearched: true,
    error: '',
  }
}

export function failDashboardSearch(state) {
  return {
    ...state,
    results: [],
    isSearching: false,
    hasSearched: true,
    error: DASHBOARD_SEARCH_MESSAGES.failure,
  }
}

export function clearDashboardSearch(state) {
  return createDashboardSearchState()
}

export function dashboardSearchStatus(state) {
  if (state.isSearching) return { kind: 'searching', message: DASHBOARD_SEARCH_MESSAGES.searching }
  if (state.error) return { kind: 'error', message: DASHBOARD_SEARCH_MESSAGES.failure }
  if (state.hasSearched && !state.results.length) {
    return { kind: 'empty', message: DASHBOARD_SEARCH_MESSAGES.noResults }
  }
  return { kind: 'idle', message: '' }
}
