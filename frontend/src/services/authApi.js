import { apiRequest, clearAuthTokens, setAuthTokens } from './apiClient.js'

export const authApi = {
  me() {
    return apiRequest('/api/auth/me/')
  },
  register(payload) {
    return apiRequest('/api/auth/register/', {
      method: 'POST',
      body: payload,
    })
  },
  async login(payload) {
    const response = await apiRequest('/api/auth/login/', {
      method: 'POST',
      body: payload,
    })
    setAuthTokens({
      access: response.access,
      refresh: response.refresh,
    })
    return response.user
  },
  async logout() {
    try {
      await apiRequest('/api/auth/logout/', {
        method: 'POST',
      })
    } finally {
      clearAuthTokens()
    }
    return { detail: 'Logged out.' }
  },
}
