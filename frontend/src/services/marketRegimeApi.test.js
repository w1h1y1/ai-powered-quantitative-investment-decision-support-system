import assert from 'node:assert/strict'
import test from 'node:test'
import { marketRegimeApi } from './marketRegimeApi.js'

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

test('Market Regime 200 response resolves normally with one request', async (t) => {
  let requestCount = 0
  t.mock.method(globalThis, 'fetch', async () => {
    requestCount += 1
    return jsonResponse({
      symbol: 'AAPL',
      regime_available: true,
      regime: 'high_volatility',
    })
  })

  const response = await marketRegimeApi.get({ symbol: 'AAPL' })

  assert.equal(response.symbol, 'AAPL')
  assert.equal(response.regime, 'high_volatility')
  assert.equal(requestCount, 1)
})

test('Market Regime HTTP 500 rejects once without automatic retry', async (t) => {
  let requestCount = 0
  t.mock.method(globalThis, 'fetch', async () => {
    requestCount += 1
    return jsonResponse({ detail: 'Internal market regime failure.' }, 500)
  })

  await assert.rejects(
    marketRegimeApi.get({ symbol: 'ERR500' }),
    (error) => {
      assert.equal(error.name, 'ApiError')
      assert.equal(error.status, 500)
      assert.equal(error.message, 'Internal market regime failure.')
      return true
    },
  )
  assert.equal(requestCount, 1)
})

test('Market Regime HTTP 429 rejects once and permits one later manual retry', async (t) => {
  let requestCount = 0
  t.mock.method(globalThis, 'fetch', async () => {
    requestCount += 1
    if (requestCount === 1) {
      return jsonResponse({ detail: 'Market data provider rate limit reached.' }, 429)
    }
    return jsonResponse({
      symbol: 'RATE429',
      regime_available: true,
      regime: 'sideways_range',
    })
  })

  await assert.rejects(
    marketRegimeApi.get({ symbol: 'RATE429' }),
    (error) => {
      assert.equal(error.name, 'ApiError')
      assert.equal(error.status, 429)
      assert.equal(error.message, 'Market data provider rate limit reached.')
      return true
    },
  )
  assert.equal(requestCount, 1)

  const retryResponse = await marketRegimeApi.get({ symbol: 'RATE429' })
  assert.equal(retryResponse.regime, 'sideways_range')
  assert.equal(requestCount, 2)
})

test('Market Regime network failure becomes a single status-zero ApiError', async (t) => {
  let requestCount = 0
  t.mock.method(globalThis, 'fetch', async () => {
    requestCount += 1
    throw new TypeError('socket disconnected')
  })

  await assert.rejects(
    marketRegimeApi.get({ symbol: 'NETWORK' }),
    (error) => {
      assert.equal(error.name, 'ApiError')
      assert.equal(error.status, 0)
      assert.equal(error.message, 'Unable to connect to the server. Please try again later.')
      return true
    },
  )
  assert.equal(requestCount, 1)
})
