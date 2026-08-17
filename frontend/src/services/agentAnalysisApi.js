import { apiRequest } from './apiClient.js'

export const agentAnalysisApi = {
  analyze({ symbol }) {
    const normalizedSymbol = String(symbol ?? '').trim().toUpperCase()
    return apiRequest('/api/agent/analyze/', {
      method: 'POST',
      body: { symbol: normalizedSymbol },
    })
  },
}
