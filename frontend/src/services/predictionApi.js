import { apiRequest } from './apiClient'

export const predictionApi = {
  generate(payload) {
    return apiRequest('/api/predictions/generate/', {
      method: 'POST',
      body: payload,
      cache: 'no-store',
    })
  },
}
