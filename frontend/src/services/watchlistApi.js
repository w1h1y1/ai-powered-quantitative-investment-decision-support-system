import { apiRequest } from './apiClient.js'

const summaryRequestPromises = new Map()

export const watchlistApi = {
  summary({ refresh = false } = {}) {
    const query = new URLSearchParams()
    if (refresh) query.set('refresh', '1')
    const requestPath = `/api/watchlist/summary/${query.toString() ? `?${query.toString()}` : ''}`

    if (!summaryRequestPromises.has(requestPath)) {
      summaryRequestPromises.set(
        requestPath,
        apiRequest(requestPath, { cache: 'no-store' }).finally(() => {
          summaryRequestPromises.delete(requestPath)
        }),
      )
    }

    return summaryRequestPromises.get(requestPath)
  },
  list() {
    return apiRequest('/api/watchlists/')
  },
  items(watchlistId) {
    const query = watchlistId ? `?watchlist=${encodeURIComponent(watchlistId)}` : ''
    return apiRequest(`/api/watchlist-items/${query}`)
  },
  createItem(payload) {
    return apiRequest('/api/watchlist-items/', {
      method: 'POST',
      body: {
        watchlist: payload.watchlist,
        security_id: payload.security_id,
      },
    })
  },
  addSymbol(payload) {
    return apiRequest('/api/watchlist/add-symbol/', {
      method: 'POST',
      body: payload,
    })
  },
  removeItem(id) {
    return apiRequest(`/api/watchlist-items/${id}/`, {
      method: 'DELETE',
    })
  },
}
