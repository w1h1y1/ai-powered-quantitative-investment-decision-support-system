import { apiRequest } from './apiClient'

let marketSummaryRequestPromise = null
const dailyRequestPromises = new Map()
const quoteRequestPromises = new Map()
const quotesRequestPromises = new Map()

export const marketDataApi = {
  summary() {
    if (!marketSummaryRequestPromise) {
      marketSummaryRequestPromise = apiRequest('/api/market-data/summary/', { cache: 'no-store' })
        .finally(() => {
          marketSummaryRequestPromise = null
        })
    }
    return marketSummaryRequestPromise
  },
  quote({ securityId }) {
    const query = new URLSearchParams({
      security: String(securityId),
    })
    const requestPath = `/api/market-data/quote/?${query.toString()}`
    if (!quoteRequestPromises.has(requestPath)) {
      quoteRequestPromises.set(
        requestPath,
        apiRequest(requestPath, { cache: 'no-store' }).finally(() => {
          quoteRequestPromises.delete(requestPath)
        }),
      )
    }
    return quoteRequestPromises.get(requestPath)
  },
  quotes({ securityIds }) {
    const ids = Array.from(new Set((securityIds ?? []).map((id) => String(id)).filter(Boolean)))
    const query = new URLSearchParams({
      security_ids: ids.join(','),
    })
    const requestPath = `/api/market-data/quotes/?${query.toString()}`
    if (!quotesRequestPromises.has(requestPath)) {
      quotesRequestPromises.set(
        requestPath,
        apiRequest(requestPath, { cache: 'no-store' }).finally(() => {
          quotesRequestPromises.delete(requestPath)
        }),
      )
    }
    return quotesRequestPromises.get(requestPath)
  },
  daily({ securityId, range, startDate, endDate, interval }) {
    const query = new URLSearchParams({
      security_id: String(securityId),
      range,
    })
    if (interval) {
      query.set('interval', interval)
    }
    if (startDate) {
      query.set('start_date', startDate)
    }
    if (endDate) {
      query.set('end_date', endDate)
    }
    const requestPath = `/api/market-data/daily/?${query.toString()}`
    if (!dailyRequestPromises.has(requestPath)) {
      dailyRequestPromises.set(
        requestPath,
        apiRequest(requestPath, { cache: 'no-store' }).finally(() => {
          dailyRequestPromises.delete(requestPath)
        }),
      )
    }
    return dailyRequestPromises.get(requestPath)
  },
}
