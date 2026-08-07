import {
  exponentialMovingAverage as sharedExponentialMovingAverage,
  macdSeries as sharedMacdSeries,
  movingAverageSeries as sharedMovingAverageSeries,
  rsiSeries as sharedRsiSeries,
} from '../../utils/technicalIndicators'

export function simpleMovingAverage(values, windowSize = 5) {
  return values.map((_, index) => {
    const start = Math.max(0, index - windowSize + 1)
    const sample = values.slice(start, index + 1)
    return sample.reduce((sum, value) => sum + value, 0) / sample.length
  })
}

export function movingAverageSeries(values, period) {
  return sharedMovingAverageSeries(values, period)
}

export function exponentialMovingAverage(values, period = 5) {
  return sharedExponentialMovingAverage(values, period)
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
  return sharedMacdSeries(values, fastPeriod, slowPeriod, signalPeriod)
}

function calculateRsiValue(averageGain, averageLoss) {
  if (averageGain === 0 && averageLoss === 0) return 50
  if (averageLoss === 0) return 100
  if (averageGain === 0) return 0

  const relativeStrength = averageGain / averageLoss
  return 100 - 100 / (1 + relativeStrength)
}

export function rsiSeries(values, period = 14) {
  return sharedRsiSeries(values, period)
}

export function buildTechnicalSummary(candles, indicators = []) {
  const closes = candles.map((candle) => candle.close)
  const volumes = candles.map((candle) => candle.volume)
  const lastIndex = closes.length - 1
  const latestClose = closes[lastIndex]
  const ma5 = movingAverageSeries(closes, 5)[lastIndex]
  const ma20 = movingAverageSeries(closes, 20)[lastIndex]
  const hasTrendAverages = Number.isFinite(latestClose) && Number.isFinite(ma5) && Number.isFinite(ma20)
  const rsi = indicators.map((indicator) => indicator.rsi).findLast((value) => Number.isFinite(value))
    ?? rsiSeries(closes, 14).findLast((value) => Number.isFinite(value))
    ?? 50
  const macd = indicators.length
    ? {
      dif: indicators.map((indicator) => indicator.macd),
      dea: indicators.map((indicator) => indicator.signal),
    }
    : macdSeries(closes, 12, 26, 9)
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

  const trend = hasTrendAverages && latestClose > ma20 && ma5 > ma20
    ? { value: 'Bullish', tone: 'positive' }
    : hasTrendAverages && latestClose < ma20 && ma5 < ma20
      ? { value: 'Bearish', tone: 'negative' }
      : { value: hasTrendAverages ? 'Mixed' : 'Insufficient data', tone: 'neutral' }

  const rsiStatus = rsi >= 70
    ? { value: 'Overbought', tone: 'warning' }
    : rsi <= 30
      ? { value: 'Oversold', tone: 'warning' }
      : rsi >= 60
        ? { value: 'Neutral, close to overbought', tone: 'warning' }
        : rsi <= 40
          ? { value: 'Neutral, close to oversold', tone: 'neutral' }
          : { value: 'Neutral', tone: 'neutral' }

  const latestMacdIndex = macd.dif.findLastIndex((value, index) => (
    Number.isFinite(value) && Number.isFinite(macd.dea[index])
  ))
  const dif = latestMacdIndex >= 0 ? macd.dif[latestMacdIndex] : null
  const dea = latestMacdIndex >= 0 ? macd.dea[latestMacdIndex] : null
  const macdMomentum = dif > dea
    ? { value: 'Bullish momentum', tone: 'positive' }
    : dif < dea
      ? { value: 'Bearish momentum', tone: 'negative' }
      : { value: 'Neutral momentum', tone: 'neutral' }

  const priceDifference = hasTrendAverages ? latestClose - ma20 : null
  const priceVsMa20 = priceDifference === null
    ? { value: 'Insufficient data', tone: 'neutral' }
    : Math.abs(priceDifference) <= Math.abs(latestClose) * 0.0005
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
