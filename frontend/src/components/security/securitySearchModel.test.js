import assert from 'node:assert/strict'
import test from 'node:test'
import {
  filterLocalSecurityOptions,
  getSecuritySearchKey,
  mergeSecuritySearchOptions,
  normalizeSecuritySearchOption,
  securitySearchDebounceMs,
  securitySearchMinimumCharacters,
  securitySearchResultLimit,
} from './securitySearchModel.js'

const localSecurities = [
  { id: 1, symbol: 'AAPL', name: 'Apple Inc.', asset_type: 'STOCK', exchange: 'NASDAQ', mic_code: 'XNAS' },
  { id: 2, symbol: 'SPY', name: 'SPDR S&P 500 ETF', asset_type: 'ETF', exchange: 'NYSE Arca', mic_code: 'ARCX' },
]

test('security search constants keep remote requests deliberate and result lists bounded', () => {
  assert.equal(securitySearchMinimumCharacters, 2)
  assert.ok(securitySearchDebounceMs >= 300 && securitySearchDebounceMs <= 500)
  assert.ok(securitySearchResultLimit >= 10 && securitySearchResultLimit <= 20)
})

test('normalizes local and remote stock or ETF results without accepting unsupported assets', () => {
  const local = normalizeSecuritySearchOption(localSecurities[0])
  const remote = normalizeSecuritySearchOption({
    symbol: 'TSLA',
    name: 'Tesla Inc.',
    exchange: 'NASDAQ',
    mic_code: 'XNAS',
    instrument_type: 'Common Stock',
    source: 'remote',
  }, 'Tesla')
  const crypto = normalizeSecuritySearchOption({ symbol: 'BTC/USD', instrument_type: 'Crypto' })

  assert.equal(local.source, 'local')
  assert.equal(remote.source, 'remote')
  assert.equal(remote.search_query, 'Tesla')
  assert.equal(crypto, null)
})

test('initial local options remain available and matching remote duplicates prefer the local Security', () => {
  assert.deepEqual(filterLocalSecurityOptions(localSecurities).map((item) => item.symbol), ['AAPL', 'SPY'])

  const merged = mergeSecuritySearchOptions(localSecurities, [
    {
      id: null,
      symbol: 'AAPL',
      name: 'Apple Remote',
      exchange: 'NYSE',
      mic_code: 'XNYS',
      instrument_type: 'Common Stock',
      source: 'remote',
    },
    {
      id: null,
      symbol: 'TSLA',
      name: 'Tesla Inc.',
      exchange: 'NASDAQ',
      mic_code: 'XNAS',
      instrument_type: 'Common Stock',
      source: 'remote',
    },
  ], '')

  assert.equal(merged.filter((item) => item.symbol === 'AAPL').length, 1)
  assert.equal(merged.find((item) => item.symbol === 'AAPL').id, 1)
  assert.equal(merged.find((item) => item.symbol === 'TSLA').source, 'remote')
  assert.equal(getSecuritySearchKey(merged[0]).includes(':'), true)
})

test('merges a remote-only JPM candidate while keeping a local AAPL result local', () => {
  const remoteJpm = {
    id: null,
    symbol: 'JPM',
    name: 'JPMorgan Chase & Co.',
    exchange: 'NYSE',
    mic_code: 'XNYS',
    instrument_type: 'Common Stock',
    source: 'remote',
  }

  const jpmResults = mergeSecuritySearchOptions(localSecurities, [remoteJpm], 'JPM')
  const aaplResults = mergeSecuritySearchOptions(localSecurities, [{
    ...remoteJpm,
    symbol: 'AAPL',
    name: 'Apple Remote',
    exchange: 'NASDAQ',
    mic_code: 'XNAS',
  }], 'AAPL')

  assert.deepEqual(jpmResults.map((item) => item.symbol), ['JPM'])
  assert.equal(jpmResults[0].is_local, false)
  assert.equal(aaplResults.length, 1)
  assert.equal(aaplResults[0].id, 1)
  assert.equal(aaplResults[0].is_local, true)
})
