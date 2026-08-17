export const securitySearchDebounceMs = 400
export const securitySearchMinimumCharacters = 2
export const securitySearchResultLimit = 20

export function getSecuritySearchKey(security) {
  const symbol = String(security?.symbol ?? '').trim().toUpperCase()
  if (!symbol) return ''

  const micCode = String(security?.mic_code ?? security?.micCode ?? '').trim().toUpperCase()
  if (micCode) return `${symbol}:${micCode}`

  const exchange = String(security?.exchange ?? '').trim().toLowerCase()
  return exchange ? `${symbol}:${exchange}` : symbol
}

export function normalizeSecuritySearchOption(security, searchQuery = '') {
  if (!security) return null
  const symbol = String(security.symbol ?? '').trim().toUpperCase()
  if (!symbol) return null

  const rawAssetType = security.asset_type ?? security.assetType ?? security.type
  const instrumentType = String(
    security.instrument_type
      ?? (String(rawAssetType).toUpperCase() === 'ETF' ? 'ETF' : 'Common Stock'),
  ).trim()
  const supportedType = instrumentType.toLowerCase()
  if (!supportedType.includes('stock') && !supportedType.includes('equity') && !supportedType.includes('etf')) {
    return null
  }

  const name = String(security.name ?? security.asset ?? symbol).trim()
  const isLocal = security.is_local === true || security.source === 'local' || Number.isInteger(security.id)
  return {
    id: Number.isInteger(security.id) ? security.id : null,
    symbol,
    name,
    asset: name,
    type: supportedType.includes('etf') ? 'ETF' : 'Stock',
    exchange: String(security.exchange ?? '').trim(),
    mic_code: String(security.mic_code ?? security.micCode ?? '').trim().toUpperCase(),
    instrument_type: instrumentType,
    country: String(security.country ?? '').trim(),
    currency: String(security.currency ?? 'USD').trim().toUpperCase(),
    is_local: isLocal,
    source: isLocal ? 'local' : 'remote',
    search_query: searchQuery,
  }
}

export function filterLocalSecurityOptions(securities, query = '') {
  const normalizedQuery = query.trim().toLowerCase()
  return securities
    .map((security) => normalizeSecuritySearchOption(security))
    .filter(Boolean)
    .filter((security) => (
      !normalizedQuery
      || security.symbol.toLowerCase().includes(normalizedQuery)
      || security.name.toLowerCase().includes(normalizedQuery)
      || security.exchange.toLowerCase().includes(normalizedQuery)
    ))
    .slice(0, securitySearchResultLimit)
}

export function mergeSecuritySearchOptions(localSecurities, remoteItems, query) {
  const merged = new Map()
  const localOptions = filterLocalSecurityOptions(localSecurities, query)
  const localSymbols = new Set(localOptions.map((security) => security.symbol))
  const add = (security) => {
    const normalized = normalizeSecuritySearchOption(security, query)
    const key = getSecuritySearchKey(normalized)
    if (!key) return
    const current = merged.get(key)
    if (!current || normalized.is_local) merged.set(key, normalized)
  }

  localOptions.forEach(add)
  ;(Array.isArray(remoteItems) ? remoteItems : []).forEach((security) => {
    const normalized = normalizeSecuritySearchOption(security, query)
    if (normalized && localSymbols.has(normalized.symbol)) return
    add(normalized)
  })
  return [...merged.values()].slice(0, securitySearchResultLimit)
}
