import { apiRequest } from './apiClient.js'

const strategyEvaluationPath = '/api/strategy-evaluation/'
const requestPromises = new Map()

function normalizedSymbol(value) {
  return String(value ?? '').trim().toUpperCase()
}

export function buildStrategyEvaluationRequestPath() {
  return strategyEvaluationPath
}

export const strategyEvaluationApi = {
  evaluate({ symbol }) {
    const normalized = normalizedSymbol(symbol)
    const dedupeKey = `${strategyEvaluationPath}?symbol=${normalized}`
    if (!requestPromises.has(dedupeKey)) {
      requestPromises.set(
        dedupeKey,
        apiRequest(strategyEvaluationPath, {
          method: 'POST',
          body: { symbol: normalized },
          cache: 'no-store',
        }).finally(() => {
          requestPromises.delete(dedupeKey)
        }),
      )
    }
    return requestPromises.get(dedupeKey)
  },
}
