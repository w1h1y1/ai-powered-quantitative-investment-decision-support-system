import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { authApi } from './authApi.js'

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function createStorage() {
  const values = new Map()
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null
    },
    setItem(key, value) {
      values.set(key, String(value))
    },
    removeItem(key) {
      values.delete(key)
    },
  }
}

test('register posts directly without requesting CSRF', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options })
    return jsonResponse({ username: 'user_a', email: 'user_a@example.com' })
  })

  const response = await authApi.register({
    username: 'user_a',
    email: 'user_a@example.com',
    password: 'StrongPassword123',
    password_confirm: 'StrongPassword123',
  })

  assert.equal(response.username, 'user_a')
  assert.equal(calls.length, 1)

  const [registerCall] = calls
  assert.ok(String(registerCall.url).endsWith('/api/auth/register/'))
  assert.equal(registerCall.options.method, 'POST')
  assert.equal(registerCall.options.headers.get('X-CSRFToken'), null)
  assert.equal(registerCall.options.headers.get('Content-Type'), 'application/json')
})

test('login stores JWT tokens and returns the current user', async (t) => {
  globalThis.localStorage = createStorage()
  t.mock.method(globalThis, 'fetch', async () => jsonResponse({
    access: 'access-token-123',
    refresh: 'refresh-token-123',
    user: { id: 1, username: 'user_a', email: 'user_a@example.com' },
  }))

  const user = await authApi.login({
    username: 'user_a',
    password: 'StrongPassword123',
  })

  assert.equal(user.username, 'user_a')
  assert.equal(globalThis.localStorage.getItem('aiquant_access_token'), 'access-token-123')
  assert.equal(globalThis.localStorage.getItem('aiquant_refresh_token'), 'refresh-token-123')
})

test('me request adds JWT Bearer Authorization automatically', async (t) => {
  globalThis.localStorage = createStorage()
  globalThis.localStorage.setItem('aiquant_access_token', 'access-token-123')

  let captured
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    captured = { url, options }
    return jsonResponse({ id: 1, username: 'user_a', email: 'user_a@example.com' })
  })

  const user = await authApi.me()

  assert.equal(user.username, 'user_a')
  assert.ok(String(captured.url).endsWith('/api/auth/me/'))
  assert.equal(captured.options.headers.get('Authorization'), 'Bearer access-token-123')
})

test('logout clears stored authentication tokens', async (t) => {
  globalThis.localStorage = createStorage()
  globalThis.localStorage.setItem('aiquant_access_token', 'access-token-123')
  globalThis.localStorage.setItem('aiquant_refresh_token', 'refresh-token-123')

  let captured
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    captured = { url, options }
    return jsonResponse({ detail: 'Logged out.' })
  })

  await authApi.logout()

  assert.ok(String(captured.url).endsWith('/api/auth/logout/'))
  assert.equal(globalThis.localStorage.getItem('aiquant_access_token'), null)
  assert.equal(globalThis.localStorage.getItem('aiquant_refresh_token'), null)
})

test('me treats 401 as unauthenticated rather than a network failure', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => jsonResponse(
    { detail: 'Authentication credentials were not provided.' },
    401,
  ))

  await assert.rejects(
    authApi.me(),
    (error) => {
      assert.equal(error.name, 'ApiError')
      assert.equal(error.status, 401)
      assert.notEqual(
        error.message,
        'Unable to connect to the server. Please try again later.',
      )
      return true
    },
  )
})

test('holding API uses the unified apiRequest base URL helper', () => {
  const holdingSource = readFileSync(
    new URL('./holdingApi.js', import.meta.url),
    'utf8',
  )
  assert.match(holdingSource, /apiRequest\('\/api\/holdings\//)
  assert.doesNotMatch(holdingSource, /127\.0\.0\.1|localhost/)
})

test('business API services never hardcode localhost or backend URLs', () => {
  const serviceFiles = [
    'agentAnalysisApi.js',
    'authApi.js',
    'backtestApi.js',
    'holdingApi.js',
    'marketDataApi.js',
    'marketRegimeApi.js',
    'portfolioApi.js',
    'predictionApi.js',
    'securityApi.js',
    'strategyEvaluationApi.js',
    'transactionApi.js',
    'watchlistApi.js',
  ]

  for (const fileName of serviceFiles) {
    const source = readFileSync(new URL(`./${fileName}`, import.meta.url), 'utf8')
    assert.doesNotMatch(
      source,
      /127\.0\.0\.1|localhost:8000|aiquant-backend\.onrender\.com/,
      `${fileName} must not hardcode an API host`,
    )
  }
})

test('api client uses VITE_API_BASE_URL and JWT Bearer Authorization', () => {
  const apiClientSource = readFileSync(
    new URL('./apiClient.js', import.meta.url),
    'utf8',
  )
  assert.match(apiClientSource, /import\.meta\.env/)
  assert.match(apiClientSource, /viteEnv\.VITE_API_BASE_URL/)
  assert.match(apiClientSource, /Authorization/)
  assert.match(apiClientSource, /Bearer/)
  assert.doesNotMatch(apiClientSource, /X-CSRFToken/)
  assert.doesNotMatch(apiClientSource, /credentials:\s*'include'/)
})
