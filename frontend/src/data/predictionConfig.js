export const directionHorizonOptions = [
  { value: 1, label: '1 Trading Day' },
  { value: 5, label: '5 Trading Days' },
]

export const returnHorizonOptions = [
  { value: 5, label: '5 Trading Days' },
  { value: 10, label: '10 Trading Days' },
  { value: 20, label: '20 Trading Days' },
]

export const predictionLookbackOptions = [
  { value: 252, label: '1 Year (252 days)' },
  { value: 504, label: '2 Years (504 days)' },
  { value: 756, label: '3 Years (756 days)' },
  { value: 1260, label: '5 Years (1260 days)' },
]

export const defaultPredictionConfig = {
  symbol: '',
  classificationForecastHorizon: 1,
  regressionForecastHorizon: 10,
  lookback: 1260,
}
