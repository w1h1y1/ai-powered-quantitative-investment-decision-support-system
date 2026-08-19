import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  REGISTER_PASSWORD_CONFIRM_MISMATCH_MESSAGE,
  REGISTER_PASSWORD_HELP_TEXT,
  REGISTER_PASSWORD_LENGTH_MESSAGE,
  REGISTER_PASSWORD_NUMERIC_MESSAGE,
  validateRegisterPassword,
} from './registerPasswordRules.js'

test('Given a password shorter than 8 characters, When registering, Then the form rejects it with the length message', () => {
  const result = validateRegisterPassword('short', 'short')

  assert.equal(result.valid, false)
  assert.equal(result.fieldErrors.password, REGISTER_PASSWORD_LENGTH_MESSAGE)
})

test('Given an entirely numeric password of 8+ characters, When registering, Then the form rejects it with the numeric message', () => {
  const result = validateRegisterPassword('12345678', '12345678')

  assert.equal(result.valid, false)
  assert.equal(result.fieldErrors.password, REGISTER_PASSWORD_NUMERIC_MESSAGE)
})

test('Given a short entirely numeric password, Then the length message takes precedence over the numeric message', () => {
  const result = validateRegisterPassword('123456', '123456')

  assert.equal(result.valid, false)
  assert.equal(result.fieldErrors.password, REGISTER_PASSWORD_LENGTH_MESSAGE)
})

test('Given a valid password, When registering, Then validation passes and submission may continue', () => {
  const result = validateRegisterPassword('StrongPassword123', 'StrongPassword123')

  assert.equal(result.valid, true)
  assert.deepEqual(result.fieldErrors, {})
})

test('Given a valid password but a different confirmation, Then the mismatch error is still shown', () => {
  const result = validateRegisterPassword('StrongPassword123', 'DifferentPassword123')

  assert.equal(result.valid, false)
  assert.equal(result.fieldErrors.passwordConfirm, REGISTER_PASSWORD_CONFIRM_MISMATCH_MESSAGE)
})

test('Given an empty password, Then a required error is returned', () => {
  const result = validateRegisterPassword('', '')

  assert.equal(result.valid, false)
  assert.equal(result.fieldErrors.password, 'Password is required.')
})

test('The help text shown before typing explains both backend rules', () => {
  assert.match(REGISTER_PASSWORD_HELP_TEXT, /at least 8 characters/)
  assert.match(REGISTER_PASSWORD_HELP_TEXT, /cannot be entirely numeric/)
})

test('The Register page shows the help text before input and uses the validator on submit', () => {
  const pageSource = readFileSync(new URL('../pages/AuthPage.jsx', import.meta.url), 'utf8')
  const rulesSource = readFileSync(new URL('./registerPasswordRules.js', import.meta.url), 'utf8')

  assert.match(pageSource, /REGISTER_PASSWORD_HELP_TEXT/)
  assert.match(pageSource, /validateRegisterPassword\(/)
  assert.match(pageSource, /className="auth-hint"/)
  assert.match(rulesSource, /Password must be at least 8 characters long and cannot be entirely numeric\./)
})
