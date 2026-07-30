import {
  forecastHorizonOptions,
  historicalWindowOptions,
  predictionAssets,
} from '../../data/predictionMockData'
import Icon from '../Icon'

export default function ForecastConfiguration({ config, isLoading, isValid, onChange, onSubmit }) {
  return (
    <section className="prediction-card prediction-config-card" aria-labelledby="prediction-config-title">
      <div className="prediction-card-header">
        <div>
          <p>Forecast setup</p>
          <h2 id="prediction-config-title">Forecast Configuration</h2>
          <span>Configure a deterministic probabilistic market simulation.</span>
        </div>
      </div>

      <form className="prediction-config-form" onSubmit={onSubmit}>
        <div className="prediction-config-grid">
          <label className="prediction-field">
            <span>Asset</span>
            <select
              value={config.assetSymbol}
              disabled={isLoading}
              onChange={(event) => onChange('assetSymbol', event.target.value)}
            >
              {predictionAssets.map((asset) => (
                <option value={asset.symbol} key={asset.symbol}>
                  {asset.symbol} - {asset.name}
                </option>
              ))}
            </select>
          </label>

          <label className="prediction-field">
            <span>Forecast Horizon</span>
            <select
              value={config.horizon}
              disabled={isLoading}
              onChange={(event) => onChange('horizon', event.target.value)}
            >
              {forecastHorizonOptions.map((option) => (
                <option value={option.value} key={option.value}>{option.label}</option>
              ))}
            </select>
          </label>

          <label className="prediction-field">
            <span>Historical Window</span>
            <select
              value={config.historicalWindow}
              disabled={isLoading}
              onChange={(event) => onChange('historicalWindow', event.target.value)}
            >
              {historicalWindowOptions.map((option) => (
                <option value={option.value} key={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="prediction-config-footer">
          <div className="prediction-toggle-grid">
            <label className="prediction-toggle">
              <input
                type="checkbox"
                checked={config.includeTechnicalIndicators}
                disabled={isLoading}
                onChange={(event) => onChange('includeTechnicalIndicators', event.target.checked)}
              />
              <span aria-hidden="true" />
              <strong>Include Technical Indicators</strong>
            </label>

            <label className="prediction-toggle">
              <input
                type="checkbox"
                checked={config.includeMarketContext}
                disabled={isLoading}
                onChange={(event) => onChange('includeMarketContext', event.target.checked)}
              />
              <span aria-hidden="true" />
              <strong>Include Market Context</strong>
            </label>
          </div>

          <div className="prediction-config-actions">
            <span>Mock forecast only. No model training or trade execution.</span>
            <button type="submit" disabled={!isValid || isLoading}>
              {isLoading ? (
                <><i className="prediction-spinner" aria-hidden="true" />Generating Forecast...</>
              ) : (
                <><Icon name="prediction" />Generate Forecast</>
              )}
            </button>
          </div>
        </div>
      </form>
    </section>
  )
}
