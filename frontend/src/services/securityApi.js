import { apiRequest } from './apiClient'

export const securityApi = {
  list() {
    return apiRequest('/api/securities/')
  },
}
