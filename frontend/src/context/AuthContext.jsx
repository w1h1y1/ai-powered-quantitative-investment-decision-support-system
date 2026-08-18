import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { authApi } from '../services/authApi'

const AuthContext = createContext(null)

function isUnauthenticatedError(error) {
  return error?.status === 401 || error?.status === 403
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [authError, setAuthError] = useState('')
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    if (typeof window === 'undefined') return undefined

    const handleSessionExpired = () => {
      setAuthError('')
      setUser(null)
    }

    window.addEventListener('aiquant:session-expired', handleSessionExpired)
    return () => window.removeEventListener('aiquant:session-expired', handleSessionExpired)
  }, [])

  const refreshUser = useCallback(async () => {
    setIsLoading(true)
    try {
      const currentUser = await authApi.me()
      setAuthError('')
      setUser(currentUser)
      return currentUser
    } catch (error) {
      if (isUnauthenticatedError(error)) {
        setAuthError('')
        setUser(null)
        return null
      }
      setAuthError(error?.message || 'Unable to connect to the server. Please try again later.')
      throw error
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    let isMounted = true

    authApi.me()
      .then((currentUser) => {
        if (isMounted) {
          setAuthError('')
          setUser(currentUser)
        }
      })
      .catch((error) => {
        if (!isMounted) return

        if (isUnauthenticatedError(error)) {
          setAuthError('')
          setUser(null)
          return
        }

        setAuthError(error?.message || 'Unable to connect to the server. Please try again later.')
      })
      .finally(() => {
        if (isMounted) setIsLoading(false)
      })

    return () => {
      isMounted = false
    }
  }, [])

  const login = useCallback(async (credentials) => {
    const loginUser = await authApi.login(credentials)
    setAuthError('')
    setUser(loginUser)
    return loginUser
  }, [])

  const register = useCallback(async (payload) => {
    await authApi.register(payload)
    const loginUser = await authApi.login({
      username: payload.username,
      password: payload.password,
    })
    setAuthError('')
    setUser(loginUser)
    return loginUser
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch (error) {
      // Ignore network errors during logout; local tokens are already cleared.
    } finally {
      setAuthError('')
      setUser(null)
    }
  }, [])

  const value = useMemo(() => ({
    authError,
    user,
    isLoading,
    isAuthenticated: Boolean(user),
    login,
    logout,
    refreshUser,
    register,
  }), [authError, isLoading, login, logout, refreshUser, register, user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
