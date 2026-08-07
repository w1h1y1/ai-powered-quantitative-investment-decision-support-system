export function parseFiniteNumber(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function findLastFinite(values) {
  if (!Array.isArray(values)) return null
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (Number.isFinite(values[index])) return values[index]
  }
  return null
}

export function movingAverageSeries(values, period) {
  return values.map((_, index) => {
    if (index < period - 1) return null
    const sample = values.slice(index - period + 1, index + 1)
    if (!sample.every(Number.isFinite)) return null
    return sample.reduce((sum, value) => sum + value, 0) / period
  })
}

export function exponentialMovingAverage(values, period) {
  const multiplier = 2 / (period + 1)
  const emaValues = []
  let previousEma = null
  let seedTotal = 0
  let finiteCount = 0

  values.forEach((value) => {
    if (!Number.isFinite(value)) {
      emaValues.push(null)
      return
    }

    finiteCount += 1
    if (finiteCount < period) {
      seedTotal += value
      emaValues.push(null)
      return
    }

    if (finiteCount === period) {
      seedTotal += value
      previousEma = seedTotal / period
      emaValues.push(previousEma)
      return
    }

    previousEma = (value - previousEma) * multiplier + previousEma
    emaValues.push(previousEma)
  })

  return emaValues
}

export function macdSeries(values, fastPeriod = 12, slowPeriod = 26, signalPeriod = 9) {
  const fastEma = exponentialMovingAverage(values, fastPeriod)
  const slowEma = exponentialMovingAverage(values, slowPeriod)
  const macd = values.map((_, index) => (
    fastEma[index] === null || slowEma[index] === null ? null : fastEma[index] - slowEma[index]
  ))
  const signal = exponentialMovingAverage(macd, signalPeriod)
  const histogram = macd.map((value, index) => (
    value === null || signal[index] === null ? null : value - signal[index]
  ))

  return {
    macd,
    signal,
    histogram,
    dif: macd,
    dea: signal,
    parameters: { fastPeriod, slowPeriod, signalPeriod },
  }
}

function calculateRsiValue(averageGain, averageLoss) {
  if (averageGain === 0 && averageLoss === 0) return 50
  if (averageLoss === 0) return 100
  if (averageGain === 0) return 0

  const relativeStrength = averageGain / averageLoss
  return 100 - (100 / (1 + relativeStrength))
}

export function rsiSeries(values, period = 14) {
  const result = Array(values.length).fill(null)
  if (values.length <= period) return result

  let gainSum = 0
  let lossSum = 0

  for (let index = 1; index <= period; index += 1) {
    if (!Number.isFinite(values[index]) || !Number.isFinite(values[index - 1])) return result
    const change = values[index] - values[index - 1]
    gainSum += Math.max(change, 0)
    lossSum += Math.max(-change, 0)
  }

  let averageGain = gainSum / period
  let averageLoss = lossSum / period
  result[period] = calculateRsiValue(averageGain, averageLoss)

  for (let index = period + 1; index < values.length; index += 1) {
    if (!Number.isFinite(values[index]) || !Number.isFinite(values[index - 1])) {
      result[index] = null
      continue
    }
    const change = values[index] - values[index - 1]
    const gain = Math.max(change, 0)
    const loss = Math.max(-change, 0)
    averageGain = ((averageGain * (period - 1)) + gain) / period
    averageLoss = ((averageLoss * (period - 1)) + loss) / period
    result[index] = calculateRsiValue(averageGain, averageLoss)
  }

  return result
}

export function realizedVolatility(values, period = 20) {
  const returns = []
  for (let index = 1; index < values.length; index += 1) {
    const current = values[index]
    const previous = values[index - 1]
    if (!Number.isFinite(current) || !Number.isFinite(previous) || previous === 0) continue
    returns.push((current - previous) / previous)
  }

  if (!returns.length) return null
  const sample = returns.slice(-period)
  const mean = sample.reduce((sum, value) => sum + value, 0) / sample.length
  const variance = sample.reduce((sum, value) => sum + ((value - mean) ** 2), 0) / sample.length
  return Math.sqrt(variance) * 100
}
