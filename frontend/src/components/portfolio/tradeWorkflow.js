const quantityScale = 4
const moneyScale = 2
const moneyMultiplier = 10n ** BigInt(moneyScale)
const moneyToGrossMultiplier = 10n ** BigInt(quantityScale)
const centsFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

function normalizeDecimalInput(value) {
  return String(value ?? '').trim()
}

function parseDecimalInput(value, { maxDecimalPlaces, allowZero = false }) {
  const text = normalizeDecimalInput(value)
  if (!/^\d+(?:\.\d*)?$/.test(text)) return { ok: false, reason: 'invalid' }

  const [wholePart, decimalPart = ''] = text.split('.')
  if (decimalPart.length > maxDecimalPlaces) return { ok: false, reason: 'precision' }

  const scaleMultiplier = 10n ** BigInt(maxDecimalPlaces)
  const wholeUnits = BigInt(wholePart || '0') * scaleMultiplier
  const paddedDecimal = decimalPart.padEnd(maxDecimalPlaces, '0')
  const decimalUnits = paddedDecimal ? BigInt(paddedDecimal) : 0n
  const units = wholeUnits + decimalUnits

  if (!allowZero && units <= 0n) return { ok: false, reason: 'non_positive' }
  return { ok: true, text, units }
}

function parseQuantityInput(value) {
  return parseDecimalInput(value, { maxDecimalPlaces: quantityScale })
}

function parseMoneyInput(value, { allowZero = false } = {}) {
  return parseDecimalInput(value, { maxDecimalPlaces: moneyScale, allowZero })
}

function isBlank(value) {
  return value === '' || value === undefined || value === null
}

function formatQuantityForMessage(value) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '0'
  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits: 4,
  }).format(parsed)
}

function scaledAmountToRoundedCents(amount) {
  return (amount + (moneyToGrossMultiplier / 2n)) / moneyToGrossMultiplier
}

function formatCents(cents) {
  return centsFormatter.format(Number(cents) / Number(moneyMultiplier))
}

function buildGrossProceedsUnits(quantityUnits, priceCents) {
  return quantityUnits * priceCents
}

function buildFeeGrossUnits(feeCents) {
  return feeCents * moneyToGrossMultiplier
}

export function buildTradeEstimate(values) {
  const quantity = parseQuantityInput(values?.quantity)
  const price = parseMoneyInput(values?.price)
  const fee = isBlank(values?.fee)
    ? { ok: true, units: 0n }
    : parseMoneyInput(values?.fee, { allowZero: true })

  if (!quantity.ok || !price.ok || !fee.ok) {
    return {
      hasEstimate: false,
      amountText: formatCents(0n),
      isNegativeProceeds: false,
    }
  }

  const grossProceeds = buildGrossProceedsUnits(quantity.units, price.units)
  const feeAmount = buildFeeGrossUnits(fee.units)
  const isSell = values?.transactionType === 'SELL'
  const rawAmount = isSell ? grossProceeds - feeAmount : grossProceeds + feeAmount
  const displayAmount = rawAmount < 0n ? 0n : rawAmount

  return {
    hasEstimate: true,
    amountText: formatCents(scaledAmountToRoundedCents(displayAmount)),
    isNegativeProceeds: rawAmount < 0n,
  }
}

function normalizeDateTime(value) {
  if (!value) return null
  const parsedDate = new Date(value)
  if (Number.isNaN(parsedDate.getTime())) return null
  return parsedDate.toISOString()
}

export function validateTradeFields(values) {
  const fieldErrors = {}
  const formError = !values?.portfolioId
    ? 'Portfolio is unavailable. Please reload the page.'
    : !['BUY', 'SELL'].includes(values.transactionType)
      ? 'Please select a transaction type.'
      : ''

  if (!values?.securityId) fieldErrors.security = 'Please select a security.'

  if (isBlank(values?.quantity)) {
    fieldErrors.quantity = 'Quantity is required.'
  } else {
    const quantity = parseQuantityInput(values.quantity)
    if (!quantity.ok && quantity.reason === 'precision') {
      fieldErrors.quantity = 'Quantity can have up to 4 decimal places.'
    } else if (!quantity.ok) {
      fieldErrors.quantity = 'Quantity must be greater than 0.'
    }
  }

  const quantity = parseQuantityInput(values?.quantity)
  if (!fieldErrors.quantity && !quantity.ok) {
    fieldErrors.quantity = 'Quantity must be greater than 0.'
  } else if (!fieldErrors.quantity && (
    values.transactionType === 'SELL'
    && Number.isFinite(Number(values.availableQuantity))
    && Number(values.quantity) > Number(values.availableQuantity)
  )) {
    fieldErrors.quantity = `Quantity cannot exceed the available quantity of ${formatQuantityForMessage(values.availableQuantity)}.`
  }

  if (isBlank(values?.price)) {
    fieldErrors.price = 'Price is required.'
  } else {
    const price = parseMoneyInput(values.price)
    if (!price.ok && price.reason === 'precision') {
      fieldErrors.price = 'Price can have up to 2 decimal places.'
    } else if (!price.ok) {
      fieldErrors.price = 'Price must be greater than 0.'
    }
  }

  const price = parseMoneyInput(values?.price)
  if (!fieldErrors.price && !price.ok) {
    fieldErrors.price = 'Price must be greater than 0.'
  }

  if (isBlank(values?.transactionDate)) {
    fieldErrors.transactionDate = 'Transaction date is required.'
  } else if (!normalizeDateTime(values.transactionDate)) {
    fieldErrors.transactionDate = 'Please enter a valid transaction date.'
  }

  const fee = isBlank(values?.fee)
    ? { ok: true, units: 0n }
    : parseMoneyInput(values.fee, { allowZero: true })
  if (!fee.ok && fee.reason === 'precision') {
    fieldErrors.fee = 'Fee can have up to 2 decimal places.'
  } else if (!fee.ok) {
    fieldErrors.fee = 'Fee cannot be negative.'
  }

  if (
    !fieldErrors.quantity
    && !fieldErrors.price
    && !fieldErrors.fee
    && values.transactionType === 'SELL'
    && quantity.ok
    && price.ok
    && fee.ok
  ) {
    const grossProceeds = buildGrossProceedsUnits(quantity.units, price.units)
    const feeAmount = buildFeeGrossUnits(fee.units)
    if (feeAmount > grossProceeds) {
      fieldErrors.fee = 'Fee cannot exceed the gross proceeds of the sale.'
    }
  }

  const firstField = ['security', 'quantity', 'price', 'transactionDate', 'fee']
    .find((fieldName) => fieldErrors[fieldName])

  return {
    fieldErrors,
    firstField,
    formError,
    isValid: !formError && Object.keys(fieldErrors).length === 0,
  }
}

export function validateTradeInput(values) {
  const result = validateTradeFields(values)
  if (result.formError) return result.formError
  if (result.firstField) return result.fieldErrors[result.firstField]
  return ''
}

function formatBackendFieldName(fieldName) {
  const fieldLabels = {
    cash_amount: 'Cash amount',
    fee: 'Fee',
    non_field_errors: '',
    portfolio: 'Portfolio',
    price: 'Price',
    quantity: 'Quantity',
    remaining_liquidity: 'Remaining liquidity',
    security: 'Security',
    security_id: 'Security',
    transaction_date: 'Transaction date',
    transaction_type: 'Transaction type',
  }
  return fieldLabels[fieldName] ?? fieldName.replaceAll('_', ' ')
}

function stringifyBackendMessage(value) {
  if (Array.isArray(value)) return value.join(' ')
  return String(value)
}

export function normalizeTradeSubmitError(error) {
  const data = error?.data
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    const messages = Object.entries(data).map(([fieldName, value]) => {
      const label = formatBackendFieldName(fieldName)
      const message = stringifyBackendMessage(value)
      return label ? `${label}: ${message}` : message
    })
    if (messages.length) return messages.join(' ')
  }

  const message = error?.message || 'Request failed. Please try again.'
  return message.replace(
    /^(quantity|price|fee|portfolio|remaining_liquidity|security_id|transaction_date|transaction_type):\s*/i,
    (_, fieldName) => `${formatBackendFieldName(fieldName.toLowerCase())}: `,
  )
}

export function buildTradeTransactionPayload(values) {
  const quantity = parseQuantityInput(values.quantity)
  const price = parseMoneyInput(values.price)
  const fee = isBlank(values.fee)
    ? { units: 0n }
    : parseMoneyInput(values.fee, { allowZero: true })

  return {
    portfolio: values.portfolioId,
    security_id: values.securityId,
    transaction_type: values.transactionType,
    quantity: `${quantity.text}${quantity.text.includes('.') ? '' : '.'}`
      .replace(/^(\d+)(?:\.(\d*))?$/, (_, whole, decimals = '') => `${whole}.${decimals.padEnd(6, '0')}`),
    price: `${price.text}${price.text.includes('.') ? '' : '.'}`
      .replace(/^(\d+)(?:\.(\d*))?$/, (_, whole, decimals = '') => `${whole}.${decimals.padEnd(4, '0')}`),
    transaction_date: normalizeDateTime(values.transactionDate),
    fee: `${fee.units / moneyMultiplier}.${String(fee.units % moneyMultiplier).padStart(2, '0')}`,
    notes: values.notes?.trim() ?? '',
  }
}

export async function submitTradeTransaction({
  isSubmitting = false,
  reloadPortfolioData,
  reloadTransactions,
  transactionApi,
  values,
}) {
  if (isSubmitting) {
    return { ok: false, skipped: true, error: '' }
  }

  const validationError = validateTradeInput(values)
  if (validationError) {
    return { ok: false, error: validationError }
  }

  try {
    await transactionApi.create(buildTradeTransactionPayload(values))
    await Promise.all([
      reloadPortfolioData(),
      reloadTransactions(),
    ])
    return { ok: true, error: '' }
  } catch (error) {
    return {
      ok: false,
      error: normalizeTradeSubmitError(error),
    }
  }
}
