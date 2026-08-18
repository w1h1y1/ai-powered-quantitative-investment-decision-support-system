import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildStrategyEvaluationRequestPath,
  strategyEvaluationApi,
} from './strategyEvaluationApi.js'

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

test('Strategy Evaluation uses POST with only the selected symbol', async (t) => {
  let requestCount = 0
  let captured
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    requestCount += 1
    captured = { url, options }
    return jsonResponse({
      symbol: 'AAPL',
      selected_strategy: 'risk_off',
      evaluation_available: false,
    })
  })

  const response = await strategyEvaluationApi.evaluate({ symbol: 'aapl' })

  assert.equal(response.symbol, 'AAPL')
  assert.equal(response.selected_strategy, 'risk_off')
  assert.equal(requestCount, 1)
  assert.equal(captured.url, 'http://127.0.0.1:8000/api/strategy-evaluation/')
  assert.equal(captured.options.method, 'POST')
  assert.equal(captured.options.body, JSON.stringify({ symbol: 'AAPL' }))
  assert.equal(captured.options.headers.get('X-CSRFToken'), null)
})

test('concurrent identical symbol requests reuse one in-flight POST', async (t) => {
  let requestCount = 0
  t.mock.method(globalThis, 'fetch', async (url) => {
    requestCount += 1
    return jsonResponse({ symbol: 'JPM', selected_strategy: 'mean_reversion' })
  })

  const first = strategyEvaluationApi.evaluate({ symbol: 'JPM' })
  const second = strategyEvaluationApi.evaluate({ symbol: 'JPM' })
  const [firstResponse, secondResponse] = await Promise.all([first, second])

  assert.equal(firstResponse.symbol, 'JPM')
  assert.equal(secondResponse.symbol, 'JPM')
  assert.equal(requestCount, 1)
})

test('Strategy Evaluation HTTP 500 rejects once without automatic retry', async (t) => {
  let requestCount = 0
  t.mock.method(globalThis, 'fetch', async (url) => {
    requestCount += 1
    return jsonResponse({ detail: 'Internal strategy evaluation failure.' }, 500)
  })

  await assert.rejects(
    strategyEvaluationApi.evaluate({ symbol: 'ERR500' }),
    (error) => {
      assert.equal(error.name, 'ApiError')
      assert.equal(error.status, 500)
      assert.equal(error.message, 'Internal strategy evaluation failure.')
      return true
    },
  )
  assert.equal(requestCount, 1)
})

test('Strategy Evaluation HTTP 429 rejects once and permits one later manual retry', async (t) => {
  let requestCount = 0
  t.mock.method(globalThis, 'fetch', async (url) => {
    requestCount += 1
    if (requestCount === 1) {
      return jsonResponse({ detail: 'Market data provider rate limit reached.' }, 429)
    }
    return jsonResponse({
      symbol: 'RATE429',
      selected_strategy: 'mean_reversion',
      evaluation_available: true,
    })
  })

  await assert.rejects(
    strategyEvaluationApi.evaluate({ symbol: 'RATE429' }),
    (error) => {
      assert.equal(error.name, 'ApiError')
      assert.equal(error.status, 429)
      assert.equal(error.message, 'Market data provider rate limit reached.')
      return true
    },
  )
  assert.equal(requestCount, 1)

  const retryResponse = await strategyEvaluationApi.evaluate({ symbol: 'RATE429' })
  assert.equal(retryResponse.selected_strategy, 'mean_reversion')
  assert.equal(requestCount, 2)
})

test('Strategy Evaluation network failure becomes a single status-zero ApiError', async (t) => {
  let requestCount = 0
  t.mock.method(globalThis, 'fetch', async () => {
    requestCount += 1
    throw new TypeError('socket disconnected')
  })

  await assert.rejects(
    strategyEvaluationApi.evaluate({ symbol: 'NETWORK' }),
    (error) => {
      assert.equal(error.name, 'ApiError')
      assert.equal(error.status, 0)
      assert.equal(error.message, 'Unable to connect to the server. Please try again later.')
      return true
    },
  )
  assert.equal(requestCount, 1)
})

test('request path is the fixed POST endpoint without query parameters', () => {
  assert.equal(buildStrategyEvaluationRequestPath(), '/api/strategy-evaluation/')
})
