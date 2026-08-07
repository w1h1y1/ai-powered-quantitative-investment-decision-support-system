import { apiRequest } from './apiClient'

export const transactionApi = {
  list(params = {}) {
    const query = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        query.set(key, String(value))
      }
    })
    const queryString = query.toString()
    return apiRequest(`/api/transactions/${queryString ? `?${queryString}` : ''}`)
  },
  create(payload) {
    return apiRequest('/api/transactions/', {
      method: 'POST',
      body: payload,
    })
  },
}
