import { apiRequest } from './apiClient'

let portfolioSummaryRequestPromise = null
const portfolioPerformanceRequestPromises = new Map()

function buildPortfolioPerformancePath(range, refresh = false) {
  const params = new URLSearchParams()
  params.set('range', range || '3M')
  if (refresh) params.set('refresh', '1')
  return `/api/portfolio/performance/?${params.toString()}`
}

export const portfolioApi = {
  summary() {
    if (!portfolioSummaryRequestPromise) {
      portfolioSummaryRequestPromise = apiRequest('/api/portfolio/summary/', { cache: 'no-store' })
        .finally(() => {
          portfolioSummaryRequestPromise = null
        })
    }
    return portfolioSummaryRequestPromise
  },
  funding() {
    return apiRequest('/api/portfolio/funding/', { cache: 'no-store' })
  },
  createFunding(payload) {
    return apiRequest('/api/portfolio/funding/', {
      method: 'POST',
      body: {
        flow_type: payload.flow_type,
        amount: payload.amount,
        transaction_date: payload.transaction_date,
        note: payload.note,
      },
    })
  },
  performance(range, options = {}) {
    const path = buildPortfolioPerformancePath(range, options.refresh)
    if (!portfolioPerformanceRequestPromises.has(path)) {
      const requestPromise = apiRequest(path, { cache: 'no-store' })
        .finally(() => {
          portfolioPerformanceRequestPromises.delete(path)
        })
      portfolioPerformanceRequestPromises.set(path, requestPromise)
    }
    return portfolioPerformanceRequestPromises.get(path)
  },
  list() {
    return apiRequest('/api/portfolios/')
  },
  create(payload) {
    return apiRequest('/api/portfolios/', {
      method: 'POST',
      body: {
        name: payload.name,
        available_funds: payload.available_funds,
      },
    })
  },
  resetTestData() {
    return apiRequest('/api/portfolio/reset-test-data/', {
      method: 'POST',
    })
  },
}
