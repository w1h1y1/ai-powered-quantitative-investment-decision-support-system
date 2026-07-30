import { apiRequest } from './apiClient'

export const holdingApi = {
  list() {
    return apiRequest('/api/holdings/')
  },
  create(payload) {
    return apiRequest('/api/holdings/', {
      method: 'POST',
      body: {
        security: payload.security,
        quantity: payload.quantity,
        average_price: payload.average_price,
      },
    })
  },
  update(id, payload) {
    return apiRequest(`/api/holdings/${id}/`, {
      method: 'PATCH',
      body: {
        quantity: payload.quantity,
        average_price: payload.average_price,
      },
    })
  },
  remove(id) {
    return apiRequest(`/api/holdings/${id}/`, {
      method: 'DELETE',
    })
  },
}
