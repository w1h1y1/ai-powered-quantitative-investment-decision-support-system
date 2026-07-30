import { apiRequest } from './apiClient'

export const transactionApi = {
  list() {
    return apiRequest('/api/transactions/')
  },
  create(payload) {
    return apiRequest('/api/transactions/', {
      method: 'POST',
      body: payload,
    })
  },
}
