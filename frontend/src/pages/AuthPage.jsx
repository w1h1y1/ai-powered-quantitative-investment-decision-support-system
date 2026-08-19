import { useEffect, useMemo, useState } from 'react'
import Icon from '../components/Icon'
import {
  REGISTER_PASSWORD_HELP_TEXT,
  validateRegisterPassword,
} from '../utils/registerPasswordRules'

const emptyForm = {
  username: '',
  email: '',
  password: '',
  password_confirm: '',
}

const fallbackErrorMessage = 'Request failed. Please try again.'

function normalizeMessages(value) {
  if (!value) return []
  return Array.isArray(value) ? value.map(String) : [String(value)]
}

function getRegisterErrorMessage(apiError) {
  const data = apiError?.data
  if (!data || typeof data !== 'object') return fallbackErrorMessage

  const messages = [
    ...normalizeMessages(data.username),
    ...normalizeMessages(data.email),
    ...normalizeMessages(data.password),
    ...normalizeMessages(data.password_confirm),
    ...normalizeMessages(data.non_field_errors),
  ].filter(Boolean)

  return messages.length ? messages.join(' ') : fallbackErrorMessage
}

export default function AuthPage({ mode, onModeChange, onLogin, onRegister }) {
  const isRegister = mode === 'register'
  const [form, setForm] = useState(emptyForm)
  const [error, setError] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
  const [isSubmitting, setIsSubmitting] = useState(false)

  const title = isRegister ? 'Create your account' : 'Sign in to AI Quant'
  const submitLabel = isRegister ? 'Create account' : 'Sign in'
  const switchCopy = isRegister ? 'Already have an account?' : 'Need an account?'
  const switchLabel = isRegister ? 'Sign in' : 'Create one'

  const canSubmit = useMemo(() => {
    if (!form.username || !form.password) return false
    if (isRegister && (!form.email || !form.password_confirm)) return false
    return true
  }, [form.email, form.password, form.password_confirm, form.username, isRegister])

  useEffect(() => {
    setError('')
    setFieldErrors({})
    setForm(emptyForm)
  }, [mode])

  const updateField = (event) => {
    const { name, value } = event.target
    setForm((current) => ({ ...current, [name]: value }))
    const fieldKey = name === 'password' ? 'password' : name === 'password_confirm' ? 'passwordConfirm' : null
    if (fieldKey) {
      setFieldErrors((current) => {
        if (!current[fieldKey]) return current
        const next = { ...current }
        delete next[fieldKey]
        return next
      })
    }
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!canSubmit || isSubmitting) return

    setError('')
    if (isRegister) {
      const validation = validateRegisterPassword(form.password, form.password_confirm)
      if (!validation.valid) {
        setFieldErrors(validation.fieldErrors)
        return
      }
    }
    setFieldErrors({})
    setIsSubmitting(true)
    try {
      if (isRegister) {
        await onRegister({
          username: form.username.trim(),
          email: form.email.trim(),
          password: form.password,
          password_confirm: form.password_confirm,
        })
      } else {
        await onLogin({
          username: form.username.trim(),
          password: form.password,
        })
      }
    } catch (apiError) {
      setError(isRegister ? getRegisterErrorMessage(apiError) : apiError.message || fallbackErrorMessage)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="auth-screen">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="auth-brand">
          <span className="brand-mark" aria-hidden="true">
            <Icon name="brand" />
          </span>
          <span>
            <strong>AI Quant</strong>
            <small>Investment Intelligence</small>
          </span>
        </div>

        <div className="auth-heading">
          <p>Account access</p>
          <h1 id="auth-title">{title}</h1>
        </div>

        <div className="auth-tabs" role="tablist" aria-label="Authentication mode">
          <button
            type="button"
            className={!isRegister ? 'is-active' : ''}
            onClick={() => onModeChange('login')}
          >
            Sign in
          </button>
          <button
            type="button"
            className={isRegister ? 'is-active' : ''}
            onClick={() => onModeChange('register')}
          >
            Register
          </button>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            <span>Username</span>
            <input
              autoComplete="username"
              name="username"
              onChange={updateField}
              required
              type="text"
              value={form.username}
            />
          </label>

          {isRegister && (
            <label>
              <span>Email</span>
              <input
                autoComplete="email"
                name="email"
                onChange={updateField}
                required
                type="email"
                value={form.email}
              />
            </label>
          )}

          <label>
            <span>Password</span>
            <input
              autoComplete={isRegister ? 'new-password' : 'current-password'}
              name="password"
              onChange={updateField}
              required
              type="password"
              value={form.password}
            />
            {isRegister && (
              <small className="auth-hint">{REGISTER_PASSWORD_HELP_TEXT}</small>
            )}
            {isRegister && fieldErrors.password && (
              <small className="auth-field-error" role="alert">{fieldErrors.password}</small>
            )}
          </label>

          {isRegister && (
            <label>
              <span>Confirm password</span>
              <input
                autoComplete="new-password"
                name="password_confirm"
                onChange={updateField}
                required
                type="password"
                value={form.password_confirm}
              />
              {fieldErrors.passwordConfirm && (
                <small className="auth-field-error" role="alert">{fieldErrors.passwordConfirm}</small>
              )}
            </label>
          )}

          {error && (
            <div className="auth-error" role="alert">
              {error}
            </div>
          )}

          <button className="auth-submit" disabled={!canSubmit || isSubmitting} type="submit">
            {isSubmitting ? 'Please wait...' : submitLabel}
          </button>
        </form>

        <p className="auth-switch">
          <span>{switchCopy}</span>
          <button type="button" onClick={() => onModeChange(isRegister ? 'login' : 'register')}>
            {switchLabel}
          </button>
        </p>
      </section>
    </main>
  )
}
