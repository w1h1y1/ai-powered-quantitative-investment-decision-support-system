export function simpleMovingAverage(values, windowSize = 5) {
  return values.map((_, index) => {
    const start = Math.max(0, index - windowSize + 1)
    const sample = values.slice(start, index + 1)
    return sample.reduce((sum, value) => sum + value, 0) / sample.length
  })
}

// TODO: Use historical warm-up bars when connected to backend market data.
export function movingAverageSeries(values, period) {
  return values.map((_, index) => {
    if (index < period - 1) return null
    const sample = values.slice(index - period + 1, index + 1)
    return sample.reduce((sum, value) => sum + value, 0) / period
  })
}

export function exponentialMovingAverage(values, period = 5) {
  const multiplier = 2 / (period + 1)
  const result = [values[0]]

  for (let index = 1; index < values.length; index += 1) {
    result.push((values[index] - result[index - 1]) * multiplier + result[index - 1])
  }

  return result
}

export function bollingerBands(values, windowSize = 5, multiplier = 1.7) {
  const middle = simpleMovingAverage(values, windowSize)
  const upper = []
  const lower = []

  values.forEach((_, index) => {
    const start = Math.max(0, index - windowSize + 1)
    const sample = values.slice(start, index + 1)
    const mean = middle[index]
    const variance = sample.reduce((sum, value) => sum + (value - mean) ** 2, 0) / sample.length
    const deviation = Math.sqrt(variance) * multiplier
    upper.push(mean + deviation)
    lower.push(mean - deviation)
  })

  return { middle, upper, lower }
}

export function bollingerOverlaySeries(values, period = 20, multiplier = 2) {
  const middle = movingAverageSeries(values, period)
  const upper = Array(values.length).fill(null)
  const lower = Array(values.length).fill(null)

  values.forEach((_, index) => {
    if (index < period - 1) return
    const sample = values.slice(index - period + 1, index + 1)
    const mean = middle[index]
    const variance = sample.reduce((sum, value) => sum + (value - mean) ** 2, 0) / period
    const deviation = Math.sqrt(variance) * multiplier
    upper[index] = mean + deviation
    lower[index] = mean - deviation
  })

  return { middle, upper, lower }
}

export function macdSeries(values, fastPeriod = 12, slowPeriod = 26, signalPeriod = 9) {
  const fastEma = exponentialMovingAverage(values, fastPeriod)
  const slowEma = exponentialMovingAverage(values, slowPeriod)
  const dif = fastEma.map((value, index) => value - slowEma[index])
  const dea = exponentialMovingAverage(dif, signalPeriod)
  const histogram = dif.map((value, index) => value - dea[index])

  return {
    dif,
    dea,
    histogram,
    parameters: { fastPeriod, slowPeriod, signalPeriod },
  }
}

function calculateRsiValue(averageGain, averageLoss) {
  if (averageGain === 0 && averageLoss === 0) return 50
  if (averageLoss === 0) return 100
  if (averageGain === 0) return 0

  const relativeStrength = averageGain / averageLoss
  return 100 - 100 / (1 + relativeStrength)
}

export function rsiSeries(values, period = 14) {
  const result = Array(values.length).fill(null)
  if (values.length <= period) return result

  let gainSum = 0
  let lossSum = 0

  for (let index = 1; index <= period; index += 1) {
    const change = values[index] - values[index - 1]
    if (change >= 0) gainSum += change
    else lossSum += Math.abs(change)
  }

  let averageGain = gainSum / period
  let averageLoss = lossSum / period
  result[period] = calculateRsiValue(averageGain, averageLoss)

  for (let index = period + 1; index < values.length; index += 1) {
    const change = values[index] - values[index - 1]
    const gain = Math.max(change, 0)
    const loss = Math.max(-change, 0)
    averageGain = (averageGain * (period - 1) + gain) / period
    averageLoss = (averageLoss * (period - 1) + loss) / period
    result[index] = calculateRsiValue(averageGain, averageLoss)
  }

  return result
}

export function buildTechnicalSummary(candles) {
  const closes = candles.map((candle) => candle.close)
  const volumes = candles.map((candle) => candle.volume)
  const lastIndex = closes.length - 1
  const latestClose = closes[lastIndex]
  const ma5 = movingAverageSeries(closes, 5)[lastIndex]
  const ma20 = movingAverageSeries(closes, 20)[lastIndex]
  const rsi = rsiSeries(closes, 14).findLast((value) => Number.isFinite(value)) ?? 50
  const macd = macdSeries(closes, 12, 26, 9)
  const bollinger = bollingerOverlaySeries(closes, 20, 2)
  const upper = bollinger.upper[lastIndex]
  const middle = bollinger.middle[lastIndex]
  const lower = bollinger.lower[lastIndex]
  const recentVolumes = volumes.slice(-20)
  const averageVolume = recentVolumes.reduce((sum, value) => sum + value, 0) / Math.max(recentVolumes.length, 1)
  const volumeRatio = volumes[lastIndex] / Math.max(averageVolume, 1)
  const bandwidth = Number.isFinite(upper) && Number.isFinite(lower) && Number.isFinite(middle)
    ? ((upper - lower) / Math.max(Math.abs(middle), 0.01)) * 100
    : 0

  const trend = latestClose > ma20 && ma5 > ma20
    ? { value: 'Bullish', tone: 'positive' }
    : latestClose < ma20 && ma5 < ma20
      ? { value: 'Bearish', tone: 'negative' }
      : { value: 'Mixed', tone: 'neutral' }

  const rsiStatus = rsi >= 70
    ? { value: 'Overbought', tone: 'warning' }
    : rsi <= 30
      ? { value: 'Oversold', tone: 'warning' }
      : rsi >= 60
        ? { value: 'Neutral, close to overbought', tone: 'warning' }
        : rsi <= 40
          ? { value: 'Neutral, close to oversold', tone: 'neutral' }
          : { value: 'Neutral', tone: 'neutral' }

  const dif = macd.dif[lastIndex]
  const dea = macd.dea[lastIndex]
  const macdMomentum = dif > dea
    ? { value: 'Bullish momentum', tone: 'positive' }
    : dif < dea
      ? { value: 'Bearish momentum', tone: 'negative' }
      : { value: 'Neutral momentum', tone: 'neutral' }

  const priceDifference = latestClose - ma20
  const priceVsMa20 = Math.abs(priceDifference) <= Math.abs(latestClose) * 0.0005
    ? { value: 'At MA20', tone: 'neutral' }
    : priceDifference > 0
      ? { value: 'Above MA20', tone: 'positive' }
      : { value: 'Below MA20', tone: 'negative' }

  const volatility = bandwidth < 2
    ? { value: 'Low', tone: 'neutral' }
    : bandwidth <= 5
      ? { value: 'Moderate', tone: 'neutral' }
      : { value: 'High', tone: 'warning' }

  const volumeActivity = volumeRatio < 0.75
    ? { value: 'Quiet', tone: 'neutral' }
    : volumeRatio <= 1.25
      ? { value: 'Normal', tone: 'neutral' }
      : { value: 'Elevated', tone: 'warning' }

  return [
    { label: 'Trend', ...trend },
    { label: 'RSI Status', ...rsiStatus },
    { label: 'MACD Momentum', ...macdMomentum },
    { label: 'Price vs MA20', ...priceVsMa20 },
    { label: 'Volatility', ...volatility },
    { label: 'Volume Activity', ...volumeActivity },
  ]
}

export function getIndicatorSeries(indicator, values) {
  if (indicator === 'ma') return { primary: simpleMovingAverage(values, 5) }
  if (indicator === 'ema') return { primary: exponentialMovingAverage(values, 5) }
  if (indicator === 'bollinger') return bollingerBands(values)
  if (indicator === 'macd') return macdSeries(values, 12, 26, 9)
  if (indicator === 'rsi') return { primary: rsiSeries(values, 14), period: 14 }
  return { primary: values }
}

export function createLinePath(values, xScale, yScale) {
  return values.map((value, index) => `${index === 0 ? 'M' : 'L'} ${xScale(index)} ${yScale(value)}`).join(' ')
}

export function createDefinedLinePath(values, xScale, yScale) {
  let drawing = false

  return values
    .map((value, index) => {
      if (!Number.isFinite(value)) {
        drawing = false
        return ''
      }

      const command = drawing ? 'L' : 'M'
      drawing = true
      return `${command} ${xScale(index)} ${yScale(value)}`
    })
    .filter(Boolean)
    .join(' ')
}

export function formatCompactVolume(value) {
  if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`
  if (value >= 1000) return `${(value / 1000).toFixed(0)}K`
  return String(value)
}
