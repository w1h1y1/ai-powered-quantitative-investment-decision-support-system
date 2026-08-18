const defaultBaseUrl = 'http://127.0.0.1:8000'
const viteEnv = import.meta.env || {}

export const API_BASE_URL = (viteEnv.VITE_API_BASE_URL || defaultBaseUrl).replace(/\/+$/, '')

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

async function ensureCsrfToken() {
  if (!csrfRequestPromise) {
    csrfRequestPromise = fetch(buildUrl('/api/auth/csrf/'), {
      method: 'GET',
      credentials: 'include',
    }).then(async (response) => {
      if (!response.ok) {
        throw new ApiError(
          'Unable to prepare CSRF protection. Please try again.',
          response.status,
          await parseResponse(response),
        )
      }
      const data = await parseResponse(response)
      if (!data?.csrf_token) {
        throw new ApiError(
          'CSRF token missing from server response.',
          response.status,
          data,
        )
      }
      return data.csrf_token
    }).finally(() => {
      csrfRequestPromise = null
    })
  }

  try {
    return await csrfRequestPromise
  } catch (error) {
    throw error instanceof ApiError
      ? error
      : new ApiError(networkErrorMessage, 0, null)
  }
}

export async function apiRequest(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const isUnsafeMethod = !['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method)
  const headers = new Headers(options.headers || {})

  if (isUnsafeMethod) {
    headers.set('X-CSRFToken', await ensureCsrfToken())
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
