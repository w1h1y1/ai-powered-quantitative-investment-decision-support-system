import assert from 'node:assert/strict'
import test from 'node:test'
import { agentAnalysisApi } from './agentAnalysisApi.js'

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

test('Generate AI Analysis obtains CSRF token and posts symbol to Django', async (t) => {
  let captured
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    if (String(url).endsWith('/api/auth/csrf/')) {
      return jsonResponse({ detail: 'CSRF cookie set.', csrf_token: 'test-csrf-token' })
    }
    captured = { url, options }
    return jsonResponse({ symbol: 'AAPL', analysis_status: 'success', analysis: {} })
  })

  const response = await agentAnalysisApi.analyze({ symbol: 'aapl' })

  assert.equal(response.symbol, 'AAPL')
  assert.equal(captured.url, 'http://127.0.0.1:8000/api/agent/analyze/')
  assert.equal(captured.options.method, 'POST')
  assert.equal(captured.options.body, JSON.stringify({ symbol: 'AAPL' }))
  assert.equal(captured.options.headers.get('X-CSRFToken'), 'test-csrf-token')
})
