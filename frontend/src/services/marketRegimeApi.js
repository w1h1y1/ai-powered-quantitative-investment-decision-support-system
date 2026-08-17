import { apiRequest } from './apiClient.js'

const requestPromises = new Map()

export function buildMarketRegimeRequestPath(symbol) {
  const normalizedSymbol = String(symbol ?? '').trim().toUpperCase()
  const query = new URLSearchParams({ symbol: normalizedSymbol })
  return `/api/market-regime/?${query.toString()}`
}

export const marketRegimeApi = {
  get({ symbol }) {
    const requestPath = buildMarketRegimeRequestPath(symbol)
    if (!requestPromises.has(requestPath)) {
      requestPromises.set(
        requestPath,
        apiRequest(requestPath, { cache: 'no-store' }).finally(() => {
          requestPromises.delete(requestPath)
        }),
      )
    }
    return requestPromises.get(requestPath)
  },
}
