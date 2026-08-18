import { apiRequest } from './apiClient.js'

export const authApi = {
  csrf() {
    return apiRequest('/api/auth/csrf/')
  },
  me() {
    return apiRequest('/api/auth/me/')
  },
  register(payload) {
    return apiRequest('/api/auth/register/', {
      method: 'POST',
      body: payload,
    })
  },
  login(payload) {
    return apiRequest('/api/auth/login/', {
      method: 'POST',
      body: payload,
    })
  },
  logout() {
    return apiRequest('/api/auth/logout/', {
      method: 'POST',
    })
  },
}
