import assert from 'node:assert/strict'
import { afterEach, beforeEach, test } from 'node:test'
import { agentAnalysisApi } from './agentAnalysisApi.js'

const originalDocument = globalThis.document

beforeEach(() => {
  globalThis.document = { cookie: 'csrftoken=test-token' }
})

afterEach(() => {
  globalThis.document = originalDocument
})

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

test('Generate AI Analysis posts symbol to the Django agent analysis endpoint', async (t) => {
  let captured
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    captured = { url, options }
    return jsonResponse({ symbol: 'AAPL', analysis_status: 'success', analysis: {} })
  })

  const response = await agentAnalysisApi.analyze({ symbol: 'aapl' })

  assert.equal(response.symbol, 'AAPL')
  assert.equal(captured.url, 'http://127.0.0.1:8000/api/agent/analyze/')
  assert.equal(captured.options.method, 'POST')
  assert.equal(captured.options.body, JSON.stringify({ symbol: 'AAPL' }))
})
