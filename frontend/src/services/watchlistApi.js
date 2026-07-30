import { apiRequest } from './apiClient'

export const watchlistApi = {
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
  removeItem(id) {
    return apiRequest(`/api/watchlist-items/${id}/`, {
      method: 'DELETE',
    })
  },
}
