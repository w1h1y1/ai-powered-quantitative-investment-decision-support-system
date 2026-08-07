import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  buildTradeEstimate,
  buildTradeTransactionPayload,
  normalizeTradeSubmitError,
  submitTradeTransaction,
  validateTradeFields,
  validateTradeInput,
} from './tradeWorkflow.js'

function baseValues(overrides = {}) {
  return {
    portfolioId: 7,
    securityId: 3,
    transactionType: 'BUY',
    quantity: '2',
    price: '410',
    transactionDate: '2026-07-24T10:30:00.000Z',
    fee: '1.25',
    notes: 'Test trade',
    ...overrides,
  }
}

test('builds BUY transaction payload for the backend serializer', () => {
  const payload = buildTradeTransactionPayload(baseValues())

  assert.deepEqual(payload, {
    portfolio: 7,
    security_id: 3,
    transaction_type: 'BUY',
    quantity: '2.000000',
    price: '410.0000',
    transaction_date: '2026-07-24T10:30:00.000Z',
    fee: '1.25',
    notes: 'Test trade',
  })
})

test('builds remote BUY payload with verified security submission fields', () => {
  const payload = buildTradeTransactionPayload(baseValues({
    securityId: undefined,
    securitySubmission: {
      symbol: 'AMD',
      name: 'Advanced Micro Devices Inc.',
      exchange: 'NASDAQ',
      mic_code: 'XNAS',
      instrument_type: 'Common Stock',
      country: 'United States',
      currency: 'USD',
      search_query: 'Advanced Micro Devices',
    },
  }))

  assert.equal(payload.security_id, undefined)
  assert.equal(payload.symbol, 'AMD')
  assert.equal(payload.name, 'Advanced Micro Devices Inc.')
  assert.equal(payload.exchange, 'NASDAQ')
  assert.equal(payload.mic_code, 'XNAS')
  assert.equal(payload.instrument_type, 'Common Stock')
  assert.equal(payload.country, 'United States')
  assert.equal(payload.currency, 'USD')
  assert.equal(payload.search_query, 'Advanced Micro Devices')
})

test('submits BUY successfully and reloads summary and transactions', async () => {
  const createdPayloads = []
  let summaryReloads = 0
  let transactionReloads = 0

  const result = await submitTradeTransaction({
    transactionApi: {
      create: async (payload) => {
        createdPayloads.push(payload)
      },
    },
    reloadPortfolioData: async () => {
      summaryReloads += 1
    },
    reloadTransactions: async () => {
      transactionReloads += 1
    },
    values: baseValues({ transactionType: 'BUY' }),
  })

  assert.equal(result.ok, true)
  assert.equal(createdPayloads[0].transaction_type, 'BUY')
  assert.equal(summaryReloads, 1)
  assert.equal(transactionReloads, 1)
})

test('submits SELL successfully', async () => {
  const createdPayloads = []

  const result = await submitTradeTransaction({
    transactionApi: {
      create: async (payload) => {
        createdPayloads.push(payload)
      },
    },
    reloadPortfolioData: async () => {},
    reloadTransactions: async () => {},
    values: baseValues({ transactionType: 'SELL', quantity: '1', price: '420' }),
  })

  assert.equal(result.ok, true)
  assert.equal(createdPayloads[0].transaction_type, 'SELL')
  assert.equal(createdPayloads[0].quantity, '1.000000')
  assert.equal(createdPayloads[0].price, '420.0000')
})

test('allows SELL fee less than gross proceeds', async () => {
  const createdPayloads = []

  const result = await submitTradeTransaction({
    transactionApi: {
      create: async (payload) => {
        createdPayloads.push(payload)
      },
    },
    reloadPortfolioData: async () => {},
    reloadTransactions: async () => {},
    values: baseValues({
      transactionType: 'SELL',
      quantity: '2',
      price: '100',
      fee: '5',
    }),
  })

  assert.equal(result.ok, true)
  assert.equal(createdPayloads[0].fee, '5.00')
})

test('allows SELL fee equal to gross proceeds and estimates zero proceeds', async () => {
  const estimate = buildTradeEstimate(baseValues({
    transactionType: 'SELL',
    quantity: '2',
    price: '100',
    fee: '200',
  }))

  assert.equal(validateTradeInput(baseValues({
    transactionType: 'SELL',
    quantity: '2',
    price: '100',
    fee: '200',
  })), '')
  assert.equal(estimate.amountText, '$0.00')
  assert.equal(estimate.isNegativeProceeds, false)
})

test('rejects SELL fee above gross proceeds before calling the API', async () => {
  let createCalls = 0
  const values = baseValues({
    transactionType: 'SELL',
    quantity: '2',
    price: '100',
    fee: '200.01',
  })

  const validation = validateTradeFields(values)
  const estimate = buildTradeEstimate(values)
  const result = await submitTradeTransaction({
    transactionApi: {
      create: async () => {
        createCalls += 1
      },
    },
    reloadPortfolioData: async () => {},
    reloadTransactions: async () => {},
    values,
  })

  assert.equal(validation.fieldErrors.fee, 'Fee cannot exceed the gross proceeds of the sale.')
  assert.equal(estimate.amountText, '$0.00')
  assert.equal(estimate.isNegativeProceeds, true)
  assert.equal(result.ok, false)
  assert.equal(result.error, 'Fee cannot exceed the gross proceeds of the sale.')
  assert.equal(createCalls, 0)
})

test('returns backend 400 validation message without reloading data', async () => {
  let summaryReloads = 0
  let transactionReloads = 0

  const result = await submitTradeTransaction({
    transactionApi: {
      create: async () => {
        throw new Error('quantity: Sell quantity cannot exceed current holding quantity.')
      },
    },
    reloadPortfolioData: async () => {
      summaryReloads += 1
    },
    reloadTransactions: async () => {
      transactionReloads += 1
    },
    values: baseValues({ transactionType: 'SELL' }),
  })

  assert.equal(result.ok, false)
  assert.equal(result.error, 'Quantity: Sell quantity cannot exceed current holding quantity.')
  assert.equal(summaryReloads, 0)
  assert.equal(transactionReloads, 0)
})

test('skips submission while a transaction is already submitting', async () => {
  let createCalls = 0

  const result = await submitTradeTransaction({
    isSubmitting: true,
    transactionApi: {
      create: async () => {
        createCalls += 1
      },
    },
    reloadPortfolioData: async () => {},
    reloadTransactions: async () => {},
    values: baseValues(),
  })

  assert.equal(result.ok, false)
  assert.equal(result.skipped, true)
  assert.equal(createCalls, 0)
})

test('validates quantity and price before submitting', () => {
  assert.equal(validateTradeInput(baseValues({ quantity: '' })), 'Quantity is required.')
  assert.equal(validateTradeInput(baseValues({ quantity: '0' })), 'Quantity must be greater than 0.')
  assert.equal(validateTradeInput(baseValues({ quantity: '-1' })), 'Quantity must be greater than 0.')
  assert.equal(validateTradeInput(baseValues({ price: '' })), 'Price is required.')
  assert.equal(validateTradeInput(baseValues({ price: '0' })), 'Price must be greater than 0.')
})

test('allows BUY security submission without local security id but keeps SELL strict', () => {
  assert.equal(validateTradeInput(baseValues({
    securityId: undefined,
    securitySubmission: {
      symbol: 'AMD',
      name: 'Advanced Micro Devices Inc.',
    },
  })), '')
  assert.equal(validateTradeInput(baseValues({
    transactionType: 'SELL',
    securityId: undefined,
    securitySubmission: {
      symbol: 'AMD',
    },
  })), 'Please select a security.')
})

test('prevents SELL quantity above the current available quantity', () => {
  assert.equal(
    validateTradeInput(baseValues({
      transactionType: 'SELL',
      quantity: '5',
      availableQuantity: 3,
    })),
    'Quantity cannot exceed the available quantity of 3.',
  )
})

test('validates fee and transaction date before submitting', () => {
  assert.equal(validateTradeInput(baseValues({ fee: '-0.01' })), 'Fee cannot be negative.')
  assert.equal(validateTradeInput(baseValues({ transactionDate: '' })), 'Transaction date is required.')
})

test('validates decimal precision for quantity, price, and fee', () => {
  assert.equal(
    validateTradeInput(baseValues({ quantity: '1.12345' })),
    'Quantity can have up to 4 decimal places.',
  )
  assert.equal(
    validateTradeInput(baseValues({ price: '410.123' })),
    'Price can have up to 2 decimal places.',
  )
  assert.equal(
    validateTradeInput(baseValues({ fee: '1.234' })),
    'Fee can have up to 2 decimal places.',
  )
})

test('accepts temporary decimal input shapes without rewriting payload values', () => {
  const payload = buildTradeTransactionPayload(baseValues({
    quantity: '1.',
    price: '410.',
    fee: '0.',
  }))

  assert.equal(validateTradeInput(baseValues({ quantity: '1.', price: '410.', fee: '0.' })), '')
  assert.equal(payload.quantity, '1.000000')
  assert.equal(payload.price, '410.0000')
  assert.equal(payload.fee, '0.00')
})

test('returns field-level English errors for the trade dialog', () => {
  const result = validateTradeFields(baseValues({
    fee: '-1',
    price: '0',
    quantity: '-2',
  }))
  const messages = Object.values(result.fieldErrors)

  assert.equal(result.isValid, false)
  assert.equal(result.fieldErrors.quantity, 'Quantity must be greater than 0.')
  assert.equal(result.fieldErrors.price, 'Price must be greater than 0.')
  assert.equal(result.fieldErrors.fee, 'Fee cannot be negative.')
  assert.equal(messages.every((message) => /^[\x00-\x7F]+$/.test(message)), true)
})

test('does not call POST /api/transactions/ when frontend validation fails', async () => {
  let createCalls = 0

  const result = await submitTradeTransaction({
    transactionApi: {
      create: async () => {
        createCalls += 1
      },
    },
    reloadPortfolioData: async () => {},
    reloadTransactions: async () => {},
    values: baseValues({ quantity: '0' }),
  })

  assert.equal(result.ok, false)
  assert.equal(result.error, 'Quantity must be greater than 0.')
  assert.equal(createCalls, 0)
})

test('normalizes backend API field errors for frontend display', () => {
  assert.equal(
    normalizeTradeSubmitError({
      data: {
        quantity: ['Sell quantity cannot exceed current holding quantity.'],
      },
    }),
    'Quantity: Sell quantity cannot exceed current holding quantity.',
  )
  assert.equal(
    normalizeTradeSubmitError(new Error('remaining_liquidity: Insufficient remaining liquidity for this transaction.')),
    'Remaining liquidity: Insufficient remaining liquidity for this transaction.',
  )
  assert.equal(
    normalizeTradeSubmitError(new Error('fee: Fee cannot exceed the gross proceeds of the sale.')),
    'Fee: Fee cannot exceed the gross proceeds of the sale.',
  )
})

test('trade dialog decimal fields use text input mode so mouse wheel does not change values', () => {
  const source = readFileSync(new URL('./TradeDialog.jsx', import.meta.url), 'utf8')
  const numericDialogSource = source.match(/<div className="portfolio-dialog-form-grid is-numeric">[\s\S]*?<label className="portfolio-dialog-notes">/)?.[0] ?? ''

  assert.equal(numericDialogSource.includes('type="number"'), false)
  assert.equal((numericDialogSource.match(/type="text"/g) ?? []).length, 3)
  assert.equal((numericDialogSource.match(/inputMode="decimal"/g) ?? []).length, 3)
  assert.equal((numericDialogSource.match(/autoComplete="off"/g) ?? []).length, 3)
  assert.equal(/min=|max=|step=/.test(numericDialogSource), false)
})
