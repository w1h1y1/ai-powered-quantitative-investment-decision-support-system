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

function isCsrfUrl(url) {
  return String(url).endsWith('/api/auth/csrf/')
}

test('register obtains CSRF token and sends credentials plus X-CSRFToken', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options })
    if (isCsrfUrl(url)) {
      return jsonResponse({ detail: 'CSRF cookie set.', csrf_token: 'csrf-token-123' })
    }
    return jsonResponse({ username: 'user_a', email: 'user_a@example.com' })
  })

  const response = await authApi.register({
    username: 'user_a',
    email: 'user_a@example.com',
    password: 'StrongPassword123',
    password_confirm: 'StrongPassword123',
  })

  assert.equal(response.username, 'user_a')
  assert.equal(calls.length, 2)

  const [csrfCall, registerCall] = calls
  assert.equal(csrfCall.options.credentials, 'include')
  assert.equal(registerCall.options.credentials, 'include')
  assert.equal(registerCall.options.method, 'POST')
  assert.equal(registerCall.options.headers.get('X-CSRFToken'), 'csrf-token-123')
  assert.equal(registerCall.options.headers.get('Content-Type'), 'application/json')
})

test('holding API uses the unified apiRequest base URL helper', () => {
  const holdingSource = readFileSync(
    new URL('./holdingApi.js', import.meta.url),
    'utf8',
  )
  assert.match(holdingSource, /apiRequest\('\/api\/holdings\//)
  assert.doesNotMatch(holdingSource, /127\.0\.0\.1|localhost/)
})

test('api client uses VITE_API_BASE_URL and credentials include for every request', () => {
  const apiClientSource = readFileSync(
    new URL('./apiClient.js', import.meta.url),
    'utf8',
  )
  assert.match(apiClientSource, /import\.meta\.env/)
  assert.match(apiClientSource, /viteEnv\.VITE_API_BASE_URL/)
  assert.match(apiClientSource, /credentials:\s*'include'/)
  assert.match(apiClientSource, /X-CSRFToken/)
})
