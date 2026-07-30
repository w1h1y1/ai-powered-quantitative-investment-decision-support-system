import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { authApi } from '../services/authApi'

const AuthContext = createContext(null)

function isUnauthenticatedError(error) {
  return error?.status === 401 || error?.status === 403
}

async function confirmCurrentSession(expectedUser) {
  const currentUser = await authApi.me()
  if (currentUser?.id !== expectedUser?.id) {
    throw new Error('Login session could not be verified. Please log out and sign in again.')
  }
  return currentUser
}

async function confirmLoggedOut() {
  try {
    await authApi.me()
  } catch (error) {
    if (isUnauthenticatedError(error)) return
    throw error
  }

  throw new Error('Logout did not clear the server session. Please refresh and try again.')
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [isLoading, setIsLoading] = useState(true)

  const refreshUser = useCallback(async () => {
    setIsLoading(true)
    try {
      const currentUser = await authApi.me()
      setUser(currentUser)
      return currentUser
    } catch (error) {
      if (isUnauthenticatedError(error)) {
        setUser(null)
        return null
      }
      setUser(null)
      throw error
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    let isMounted = true

    authApi.me()
      .then((currentUser) => {
        if (isMounted) setUser(currentUser)
      })
      .catch(() => {
        if (isMounted) setUser(null)
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
    const currentUser = await confirmCurrentSession(loginUser)
    setUser(currentUser)
    return currentUser
  }, [])

  const register = useCallback(async (payload) => {
    await authApi.register(payload)
    const currentUser = await authApi.login({
      username: payload.username,
      password: payload.password,
    })
    setUser(currentUser)
    return currentUser
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
      await confirmLoggedOut()
      setUser(null)
    } catch (error) {
      const detail = String(error?.data?.detail || error?.message || '').toLowerCase()
      const isAlreadyLoggedOut = isUnauthenticatedError(error)
        && detail.includes('authentication credentials')
      const isCsrfFailure = error?.status === 403 && detail.includes('csrf')

      if (isAlreadyLoggedOut) {
        setUser(null)
        return
      }

      if (isCsrfFailure) {
        await authApi.csrf()
        await authApi.logout()
        await confirmLoggedOut()
        setUser(null)
        return
      }

      throw error
    }
  }, [])

  const value = useMemo(() => ({
    user,
    isLoading,
    isAuthenticated: Boolean(user),
    login,
    logout,
    refreshUser,
    register,
  }), [isLoading, login, logout, refreshUser, register, user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
