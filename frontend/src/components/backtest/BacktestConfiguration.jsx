import StrategyParameters from './StrategyParameters'

function FieldError({ id, message }) {
  if (!message) return null
  return <small className="backtest-field-error" id={id}>{message}</small>
}

export default function BacktestConfiguration({
  assets,
  strategies,
  selectedAsset,
  selectedStrategy,
  config,
  errors,
  isLoading,
  onChange,
  onSubmit,
}) {
  const isInvalid = Object.keys(errors).length > 0
  const startDateError = errors.startDate ?? errors.dateRange

  return (
    <section className="backtest-card backtest-config-card" aria-labelledby="backtest-config-title">
      <div className="backtest-card-header">
        <div>
          <p>Simulation setup</p>
          <h2 id="backtest-config-title">Backtest Configuration</h2>
          <span>Configure a rule-based historical simulation using the current demo universe.</span>
        </div>
        <div className="demo-data-status" aria-label="Demo data, last updated at 16:00">
          <strong>Demo Data</strong>
          <span>Last updated: 16:00</span>
        </div>
      </div>

      <form className="backtest-config-form" onSubmit={onSubmit} noValidate>
        <div className="backtest-config-grid">
          <label className="backtest-field is-asset" htmlFor="backtest-asset">
            <span>Asset</span>
            <div className="backtest-asset-control">
              <select
                id="backtest-asset"
                value={config.symbol}
                onChange={(event) => onChange('symbol', event.target.value)}
                disabled={isLoading}
                aria-invalid={Boolean(errors.symbol)}
                aria-describedby={errors.symbol ? 'backtest-asset-error' : undefined}
              >
                {assets.map((asset) => (
                  <option value={asset.symbol} key={asset.symbol}>
                    {asset.symbol} — {asset.asset}
                  </option>
                ))}
              </select>
              <strong className={`backtest-asset-type is-${selectedAsset?.type.toLowerCase() ?? 'stock'}`}>
                {selectedAsset?.type ?? 'Stock'}
              </strong>
            </div>
            <FieldError id="backtest-asset-error" message={errors.symbol} />
          </label>

          <label className="backtest-field is-strategy" htmlFor="backtest-strategy">
            <span>Strategy</span>
            <select
              id="backtest-strategy"
              value={config.strategyId}
              onChange={(event) => onChange('strategyId', event.target.value)}
              disabled={isLoading}
              aria-invalid={Boolean(errors.strategyId)}
              aria-describedby={errors.strategyId ? 'backtest-strategy-error' : undefined}
            >
              {strategies.map((strategy) => (
                <option value={strategy.id} key={strategy.id}>{strategy.label}</option>
              ))}
            </select>
            <FieldError id="backtest-strategy-error" message={errors.strategyId} />
          </label>

          <label className="backtest-field" htmlFor="backtest-start-date">
            <span>Start date</span>
            <input
              id="backtest-start-date"
              type="date"
              value={config.startDate}
              onChange={(event) => onChange('startDate', event.target.value)}
              disabled={isLoading}
              aria-invalid={Boolean(startDateError)}
              aria-describedby={startDateError ? 'backtest-start-date-error' : undefined}
            />
            <FieldError id="backtest-start-date-error" message={startDateError} />
          </label>

          <label className="backtest-field" htmlFor="backtest-end-date">
            <span>End date</span>
            <input
              id="backtest-end-date"
              type="date"
              value={config.endDate}
              onChange={(event) => onChange('endDate', event.target.value)}
              disabled={isLoading}
              aria-invalid={Boolean(errors.endDate)}
              aria-describedby={errors.endDate ? 'backtest-end-date-error' : undefined}
            />
            <FieldError id="backtest-end-date-error" message={errors.endDate} />
          </label>

          <label className="backtest-field" htmlFor="backtest-capital">
            <span>Initial capital</span>
            <div className="backtest-input-prefix">
              <b>$</b>
              <input
                id="backtest-capital"
                type="number"
                min="0.01"
                step="100"
                value={config.initialCapital}
                onChange={(event) => onChange('initialCapital', event.target.value)}
                disabled={isLoading}
                aria-invalid={Boolean(errors.initialCapital)}
                aria-describedby={errors.initialCapital ? 'backtest-capital-error' : undefined}
              />
            </div>
            <FieldError id="backtest-capital-error" message={errors.initialCapital} />
          </label>

          <label className="backtest-field" htmlFor="backtest-fee">
            <span>Trading fee</span>
            <div className="backtest-input-suffix">
              <input
                id="backtest-fee"
                type="number"
                min="0"
                step="0.01"
                value={config.tradingFee}
                onChange={(event) => onChange('tradingFee', event.target.value)}
                disabled={isLoading}
                aria-invalid={Boolean(errors.tradingFee)}
                aria-describedby={errors.tradingFee ? 'backtest-fee-error' : undefined}
              />
              <b>%</b>
            </div>
            <FieldError id="backtest-fee-error" message={errors.tradingFee} />
          </label>
        </div>

        <div className="backtest-parameter-action-row">
          <StrategyParameters
            strategy={selectedStrategy}
            config={config}
            errors={errors}
            disabled={isLoading}
            onChange={onChange}
          />

          <div className="backtest-config-actions">
            <span>Deterministic demo results, not live market execution.</span>
            <button type="submit" disabled={isInvalid || isLoading}>
              {isLoading && <i className="backtest-loading-spinner" aria-hidden="true" />}
              {isLoading ? 'Running Backtest...' : 'Run Backtest'}
            </button>
          </div>
        </div>
      </form>
    </section>
  )
}
