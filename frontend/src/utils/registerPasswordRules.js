export const REGISTER_PASSWORD_MIN_LENGTH = 8

export const REGISTER_PASSWORD_HELP_TEXT =
  'Password must be at least 8 characters long and cannot be entirely numeric.'

export const REGISTER_PASSWORD_LENGTH_MESSAGE =
  'Password must be at least 8 characters long.'

export const REGISTER_PASSWORD_NUMERIC_MESSAGE =
  'Password cannot be entirely numeric.'

export const REGISTER_PASSWORD_CONFIRM_MISMATCH_MESSAGE =
  'Passwords do not match.'

/**
 * Lightweight client-side check for the Register page.
 *
 * This only improves UX; the Django backend remains the authoritative
 * password policy (minimum length, common-password list, numeric-only rule,
 * similarity rule when a user object is available).
 *
 * Returns { valid, fieldErrors } where fieldErrors maps 'password' and/or
 * 'passwordConfirm' to user-facing messages.
 */
export function validateRegisterPassword(password, passwordConfirm) {
  const fieldErrors = {}

  if (!password) {
    fieldErrors.password = 'Password is required.'
    return { valid: false, fieldErrors }
  }

  if (password.length < REGISTER_PASSWORD_MIN_LENGTH) {
    fieldErrors.password = REGISTER_PASSWORD_LENGTH_MESSAGE
  } else if (/^\d+$/.test(password)) {
    fieldErrors.password = REGISTER_PASSWORD_NUMERIC_MESSAGE
  }

  if (passwordConfirm && password !== passwordConfirm) {
    fieldErrors.passwordConfirm = REGISTER_PASSWORD_CONFIRM_MISMATCH_MESSAGE
  }

  return { valid: Object.keys(fieldErrors).length === 0, fieldErrors }
}
