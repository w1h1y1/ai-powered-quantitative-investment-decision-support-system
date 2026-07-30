import { apiRequest } from './apiClient'

export const marketDataApi = {
  daily({ securityId, range, startDate, endDate }) {
    const query = new URLSearchParams({
      security: String(securityId),
      range,
    })
    if (startDate) {
      query.set('start_date', startDate)
    }
    if (endDate) {
      query.set('end_date', endDate)
    }
    return apiRequest(`/api/market-data/daily/?${query.toString()}`)
  },
}
