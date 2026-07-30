import { apiRequest } from './apiClient'

export const portfolioApi = {
  summary() {
    return apiRequest('/api/portfolio/summary/')
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
}
