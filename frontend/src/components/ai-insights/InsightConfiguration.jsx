import {
  aiInsightAssets,
  analysisHorizons,
  investorObjectives,
  riskPreferences,
} from '../../data/aiInsightsMockData'

function ToggleField({ id, label, checked, disabled, onChange }) {
  return (
    <label className="ai-insights-toggle" htmlFor={id}>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span aria-hidden="true" />
      <strong>{label}</strong>
    </label>
  )
}

export default function InsightConfiguration({
  config,
  hasPredictionContext,
  isLoading,
  onChange,
  onSubmit,
}) {
  return (
    <section className="ai-insights-card ai-insights-config-card" aria-labelledby="ai-insights-config-title">
      <div className="ai-insights-card-header">
        <div>
          <p>Analysis setup</p>
          <h2 id="ai-insights-config-title">Insight Configuration</h2>
          <span>Configure a deterministic mock decision-support analysis.</span>
        </div>
      </div>

      <form className="ai-insights-config-form" onSubmit={onSubmit}>
        <div className="ai-insights-config-grid">
          <label className="ai-insights-field is-asset" htmlFor="ai-insights-asset">
            <span>Asset</span>
            <select
              id="ai-insights-asset"
              value={config.symbol}
              disabled={isLoading}
              onChange={(event) => onChange('symbol', event.target.value)}
            >
              {aiInsightAssets.map((asset) => (
                <option value={asset.symbol} key={asset.symbol}>
                  {asset.symbol} - {asset.name}
                </option>
              ))}
            </select>
          </label>

          <label className="ai-insights-field" htmlFor="ai-insights-horizon">
            <span>Analysis Horizon</span>
            <select
              id="ai-insights-horizon"
              value={config.horizon}
              disabled={isLoading}
              onChange={(event) => onChange('horizon', event.target.value)}
            >
              {analysisHorizons.map((horizon) => (
                <option value={horizon.id} key={horizon.id}>{horizon.label}</option>
              ))}
            </select>
          </label>

          <label className="ai-insights-field" htmlFor="ai-insights-objective">
            <span>Investor Objective</span>
            <select
              id="ai-insights-objective"
              value={config.objective}
              disabled={isLoading}
              onChange={(event) => onChange('objective', event.target.value)}
            >
              {investorObjectives.map((objective) => (
                <option value={objective.id} key={objective.id}>{objective.label}</option>
              ))}
            </select>
          </label>

          <label className="ai-insights-field" htmlFor="ai-insights-risk">
            <span>Risk Preference</span>
            <select
              id="ai-insights-risk"
              value={config.riskPreference}
              disabled={isLoading}
              onChange={(event) => onChange('riskPreference', event.target.value)}
            >
              {riskPreferences.map((preference) => (
                <option value={preference.id} key={preference.id}>{preference.label}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="ai-insights-config-footer">
          <div className="ai-insights-toggle-grid">
            <ToggleField
              id="ai-insights-portfolio-context"
              label="Include current portfolio exposure"
              checked={config.includePortfolio}
              disabled={isLoading}
              onChange={(value) => onChange('includePortfolio', value)}
            />
            <ToggleField
              id="ai-insights-backtest-context"
              label="Include latest backtest evidence"
              checked={config.includeBacktest}
              disabled={isLoading}
              onChange={(value) => onChange('includeBacktest', value)}
            />
            <div className="ai-insights-toggle-option">
              <ToggleField
                id="ai-insights-prediction-context"
                label="Include latest forecast"
                checked={config.includePrediction}
                disabled={isLoading || !hasPredictionContext}
                onChange={(value) => onChange('includePrediction', value)}
              />
              {!hasPredictionContext && <span>No forecast context available.</span>}
            </div>
          </div>

          <div className="ai-insights-config-actions">
            <span>Mock analysis only. No broker connection or trade execution.</span>
            <button type="submit" disabled={isLoading}>
              {isLoading && <i className="ai-insights-spinner" aria-hidden="true" />}
              {isLoading ? 'Generating Insight...' : 'Generate Insight'}
            </button>
          </div>
        </div>
      </form>
    </section>
  )
}
