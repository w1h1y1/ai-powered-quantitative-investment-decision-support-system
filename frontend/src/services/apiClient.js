const defaultBaseUrl = 'http://127.0.0.1:8000'
const viteEnv = import.meta.env || {}

export const API_BASE_URL = (viteEnv.VITE_API_BASE_URL || defaultBaseUrl).replace(/\/+$/, '')

const ACCESS_TOKEN_KEY = 'aiquant_access_token'
const REFRESH_TOKEN_KEY = 'aiquant_refresh_token'
const networkErrorMessage = 'Unable to connect to the server. Please try again later.'

let refreshRequestPromise = null

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

function getTokenStore() {
  try {
    if (typeof globalThis.localStorage !== 'undefined') return globalThis.localStorage
  } catch (error) {
    return null
  }
  return null
}

export function getAccessToken() {
  const store = getTokenStore()
  if (!store) return null
  try {
    return store.getItem(ACCESS_TOKEN_KEY)
  } catch (error) {
    return null
  }
}

function getRefreshToken() {
  const store = getTokenStore()
  if (!store) return null
  try {
    return store.getItem(REFRESH_TOKEN_KEY)
  } catch (error) {
    return null
  }
}

export function setAuthTokens({ access, refresh }) {
  const store = getTokenStore()
  if (!store) return
  try {
    if (access) store.setItem(ACCESS_TOKEN_KEY, access)
    if (refresh) store.setItem(REFRESH_TOKEN_KEY, refresh)
  } catch (error) {
    // Storage may be unavailable; the in-memory auth state still works.
  }
}

export function clearAuthTokens() {
  const store = getTokenStore()
  if (!store) return
  try {
    store.removeItem(ACCESS_TOKEN_KEY)
    store.removeItem(REFRESH_TOKEN_KEY)
  } catch (error) {
    // Ignore storage failures during logout.
  }
}

async function performRequest(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const headers = new Headers(options.headers || {})
  const hasBody = options.body !== undefined && options.body !== null
  const body = options.body

  if (hasBody && !(body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  return fetch(buildUrl(path), {
    ...options,
    method,
    headers,
    body: hasBody && !(body instanceof FormData) ? JSON.stringify(body) : body,
  })
}

async function safeFetch(path, options = {}) {
  try {
    return await performRequest(path, options)
  } catch (error) {
    throw new ApiError(networkErrorMessage, 0, null)
  }
}

function isAuthPath(path) {
  return ['/api/auth/login/', '/api/auth/register/', '/api/auth/refresh/'].includes(path)
}

async function refreshAccessToken() {
  if (refreshRequestPromise) return refreshRequestPromise

  const refresh = getRefreshToken()
  if (!refresh) {
    clearAuthTokens()
    return Promise.reject(new ApiError('Your session has expired. Please sign in again.', 401, null))
  }

  refreshRequestPromise = safeFetch('/api/auth/refresh/', {
    method: 'POST',
    body: { refresh },
  }).then(async (response) => {
    const data = await parseResponse(response)
    if (!response.ok) {
      clearAuthTokens()
      throw new ApiError(
        extractErrorMessage(data, 'Your session has expired. Please sign in again.'),
        response.status,
        data,
      )
    }
    if (!data?.access) {
      clearAuthTokens()
      throw new ApiError('Your session has expired. Please sign in again.', response.status, data)
    }
    setAuthTokens({ access: data.access })
    return data.access
  }).finally(() => {
    refreshRequestPromise = null
  })

  try {
    return await refreshRequestPromise
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError(networkErrorMessage, 0, null)
  }
}

function withAuthorization(headers) {
  const accessToken = getAccessToken()
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  return headers
}

function notifySessionExpired() {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('aiquant:session-expired'))
  }
}

export async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {})
  withAuthorization(headers)

  let response = await safeFetch(path, { ...options, headers })

  if (response.status === 401 && !isAuthPath(path)) {
    if (!getRefreshToken()) {
      notifySessionExpired()
    } else {
      try {
        const newAccessToken = await refreshAccessToken()
        const refreshedHeaders = new Headers(options.headers || {})
        refreshedHeaders.set('Authorization', `Bearer ${newAccessToken}`)
        response = await safeFetch(path, { ...options, headers: refreshedHeaders })
      } catch (error) {
        notifySessionExpired()
        throw error
      }
    }
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
