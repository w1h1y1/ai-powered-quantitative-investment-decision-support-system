export default function StrategyParameters({ strategy, config, errors, disabled, onChange }) {
  if (!strategy) return null

  return (
    <fieldset className="backtest-parameter-fieldset" disabled={disabled}>
      <legend>Strategy parameters</legend>
      <p>{strategy.description}</p>
      <p className="backtest-parameter-note">
        Risk controls the maximum planned loss if the ATR stop is reached. Exposure limits the maximum share of account equity allocated to the position.
      </p>
      <div className="backtest-parameter-grid" key={strategy.id}>
        {strategy.parameters.map((parameter) => {
          const inputId = `backtest-${parameter.key}`
          const errorId = `${inputId}-error`
          const error = errors[parameter.key]

          return (
            <label className="backtest-field" htmlFor={inputId} key={parameter.key}>
              <span>{parameter.label}</span>
              {parameter.description && (
                <small className="backtest-parameter-description">{parameter.description}</small>
              )}
              {parameter.type === 'select' ? (
                <select
                  id={inputId}
                  value={config[parameter.key]}
                  onChange={(event) => onChange(parameter.key, event.target.value)}
                  aria-invalid={Boolean(error)}
                  aria-describedby={error ? errorId : undefined}
                >
                  {parameter.options.map((option) => (
                    <option value={option.value} key={option.value}>{option.label}</option>
                  ))}
                </select>
              ) : (
                <input
                  id={inputId}
                  type="number"
                  min={parameter.min}
                  max={parameter.max}
                  step={parameter.step}
                  value={config[parameter.key]}
                  onChange={(event) => onChange(parameter.key, event.target.value)}
                  aria-invalid={Boolean(error)}
                  aria-describedby={error ? errorId : undefined}
                />
              )}
              {error && <small className="backtest-field-error" id={errorId}>{error}</small>}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}
