import { apiRequest } from './apiClient.js'

const symbolSearchCache = new Map()
const symbolSearchRequests = new Map()
const SYMBOL_SEARCH_CACHE_TTL_MS = 5 * 60 * 1000

function getSearchCacheKey(query) {
  return query.trim().toLowerCase()
}

export const securityApi = {
  list() {
    return apiRequest('/api/securities/')
  },
  sectorContext({ securityId }) {
    return apiRequest(`/api/securities/${securityId}/sector-context/`)
  },
  search(query) {
    const normalizedQuery = query.trim()
    if (normalizedQuery.length < 2) {
      return Promise.resolve({
        query: normalizedQuery,
        items: [],
        metadata: {
          query: normalizedQuery,
          count: 0,
          cache_status: 'not_used',
        },
      })
    }

    const cacheKey = getSearchCacheKey(normalizedQuery)
    const cached = symbolSearchCache.get(cacheKey)
    if (cached && Date.now() - cached.createdAt < SYMBOL_SEARCH_CACHE_TTL_MS) {
      return Promise.resolve({
        ...cached.payload,
        metadata: {
          ...(cached.payload.metadata || {}),
          client_cache_status: 'hit',
        },
      })
    }

    if (!symbolSearchRequests.has(cacheKey)) {
      const params = new URLSearchParams({ q: normalizedQuery })
      symbolSearchRequests.set(
        cacheKey,
        apiRequest(`/api/securities/search/?${params.toString()}`, { cache: 'no-store' })
          .then((payload) => {
            symbolSearchCache.set(cacheKey, {
              createdAt: Date.now(),
              payload,
            })
            return payload
          })
          .finally(() => {
            symbolSearchRequests.delete(cacheKey)
          }),
      )
    }

    return symbolSearchRequests.get(cacheKey)
  },
  resolve(selection) {
    return apiRequest('/api/securities/resolve/', {
      method: 'POST',
      body: selection,
    }).then((payload) => {
      symbolSearchCache.clear()
      return payload
    })
  },
}
