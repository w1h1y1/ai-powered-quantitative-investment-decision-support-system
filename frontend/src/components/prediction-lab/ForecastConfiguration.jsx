import {
  directionHorizonOptions,
  predictionLookbackOptions,
  returnHorizonOptions,
} from '../../data/predictionConfig'
import SecuritySearchSelect from '../security/SecuritySearchSelect'
import Icon from '../Icon'

export default function ForecastConfiguration({
  config,
  assets,
  selectedAsset,
  isAssetsLoading,
  isLoading,
  isValid,
  error,
  onChange,
  onSelectAsset,
  onSubmit,
}) {
  return (
    <section className="prediction-card prediction-config-card" aria-labelledby="prediction-config-title">
      <div className="prediction-card-header">
        <div>
          <p>Forecast setup</p>
          <h2 id="prediction-config-title">Forecast Configuration</h2>
          <span>Load real daily market data and technical indicators for a selected security.</span>
        </div>
      </div>

      <form className="prediction-config-form" onSubmit={onSubmit}>
        <div className="prediction-config-grid">
          <div className="prediction-field">
            <span>Asset</span>
            <SecuritySearchSelect
              id="prediction-asset"
              localSecurities={assets}
              selectedSecurity={selectedAsset}
              disabled={isAssetsLoading}
              invalid={Boolean(error)}
              describedBy={error ? 'prediction-asset-error' : undefined}
              onSelect={onSelectAsset}
            />
            {error && <small id="prediction-asset-error">{error}</small>}
          </div>

          <label className="prediction-field">
            <span>Direction Horizon</span>
            <select
              value={String(config.classificationForecastHorizon)}
              disabled={isLoading}
              onChange={(event) => onChange('classificationForecastHorizon', Number(event.target.value))}
            >
              {directionHorizonOptions.map((option) => (
                <option value={option.value} key={option.value}>{option.label}</option>
              ))}
            </select>
          </label>

          <label className="prediction-field">
            <span>Return Horizon</span>
            <select
              value={String(config.regressionForecastHorizon)}
              disabled={isLoading}
              onChange={(event) => onChange('regressionForecastHorizon', Number(event.target.value))}
            >
              {returnHorizonOptions.map((option) => (
                <option value={option.value} key={option.value}>{option.label}</option>
              ))}
            </select>
          </label>

          <label className="prediction-field">
            <span>Historical Lookback</span>
            <select
              value={String(config.lookback)}
              disabled={isLoading}
              onChange={(event) => onChange('lookback', Number(event.target.value))}
            >
              {predictionLookbackOptions.map((option) => (
                <option value={option.value} key={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="prediction-config-footer">
          <div className="prediction-config-actions">
            <span>Direction and return models use independent targets, purge gaps, and chronological validation.</span>
            <button type="submit" disabled={!isValid || isLoading}>
              {isLoading ? (
                <><i className="prediction-spinner" aria-hidden="true" />Running Prediction...</>
              ) : (
                <><Icon name="prediction" />Run Prediction</>
              )}
            </button>
          </div>
        </div>
      </form>
    </section>
  )
}
