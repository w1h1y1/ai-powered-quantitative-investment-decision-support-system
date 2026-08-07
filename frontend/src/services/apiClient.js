const defaultBaseUrl = 'http://127.0.0.1:8000'
const viteEnv = import.meta.env || {}

export const API_BASE_URL = (viteEnv.VITE_API_BASE_URL || defaultBaseUrl).replace(/\/+$/, '')

const csrfCookieName = 'csrftoken'
const networkErrorMessage = 'Unable to connect to the server. Please try again later.'
let csrfRequestPromise = null

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

function getCookie(name) {
  const cookies = document.cookie ? document.cookie.split('; ') : []
  const cookie = cookies.find((item) => item.startsWith(`${name}=`))
  return cookie ? decodeURIComponent(cookie.slice(name.length + 1)) : ''
}

function buildUrl(path) {
  return `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`
}

function formatFieldError(field, value) {
  const messages = Array.isArray(value) ? value.join(' ') : String(value)
  return `${field}: ${messages}`
}

function extractErrorMessage(data, fallback) {
  if (!data) return fallback
  if (typeof data === 'string') return data
  if (data.detail) return Array.isArray(data.detail) ? data.detail.join(' ') : String(data.detail)
  if (data.non_field_errors) {
    return Array.isArray(data.non_field_errors) ? data.non_field_errors.join(' ') : String(data.non_field_errors)
  }
  if (typeof data === 'object') {
    const messages = Object.entries(data).map(([field, value]) => formatFieldError(field, value))
    if (messages.length) return messages.join(' ')
  }
  return fallback
}

async function parseResponse(response) {
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) return null
  try {
    return await response.json()
  } catch (error) {
    return null
  }
}

async function ensureCsrfCookie() {
  if (getCookie(csrfCookieName)) return
  if (!csrfRequestPromise) {
    csrfRequestPromise = fetch(buildUrl('/api/auth/csrf/'), {
      method: 'GET',
      credentials: 'include',
    }).finally(() => {
      csrfRequestPromise = null
    })
  }

  let response
  try {
    response = await csrfRequestPromise
  } catch (error) {
    throw new ApiError(networkErrorMessage, 0, null)
  }
  if (!response.ok) {
    throw new ApiError('Unable to prepare CSRF protection. Please try again.', response.status, await parseResponse(response))
  }
}

export async function apiRequest(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const isUnsafeMethod = !['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method)
  const headers = new Headers(options.headers || {})

  if (isUnsafeMethod) {
    await ensureCsrfCookie()
    headers.set('X-CSRFToken', getCookie(csrfCookieName))
  }

  if (options.body !== undefined && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  let response
  try {
    response = await fetch(buildUrl(path), {
      ...options,
      method,
      credentials: 'include',
      headers,
      body: options.body !== undefined && !(options.body instanceof FormData)
        ? JSON.stringify(options.body)
        : options.body,
    })
  } catch (error) {
    throw new ApiError(networkErrorMessage, 0, null)
  }

  const data = await parseResponse(response)
  if (!response.ok) {
    throw new ApiError(
      extractErrorMessage(data, 'Request failed. Please try again.'),
      response.status,
      data,
    )
  }

  return data
}
