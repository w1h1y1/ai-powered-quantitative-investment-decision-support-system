import { apiRequest } from './apiClient.js'

export const agentAnalysisApi = {
  analyze({ symbol }) {
    const normalizedSymbol = String(symbol ?? '').trim().toUpperCase()
    return apiRequest('/api/agent/analyze/', {
      method: 'POST',
      body: { symbol: normalizedSymbol },
    })
  },
  latest({ symbol }) {
    const normalizedSymbol = String(symbol ?? '').trim().toUpperCase()
    const params = new URLSearchParams({ symbol: normalizedSymbol })
    return apiRequest(`/api/agent/analysis/latest/?${params.toString()}`)
  },
}
