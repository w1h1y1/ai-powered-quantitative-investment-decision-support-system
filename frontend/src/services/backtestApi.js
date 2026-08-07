import { apiRequest } from './apiClient'

export const backtestApi = {
  run(payload) {
    return apiRequest('/api/backtests/run/', {
      method: 'POST',
      body: payload,
      cache: 'no-store',
    })
  },
}
