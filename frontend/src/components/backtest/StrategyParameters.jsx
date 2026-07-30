export default function StrategyParameters({ strategy, config, errors, disabled, onChange }) {
  if (!strategy) return null

  return (
    <fieldset className="backtest-parameter-fieldset" disabled={disabled}>
      <legend>Strategy parameters</legend>
      <p>{strategy.description}</p>
      <div className="backtest-parameter-grid" key={strategy.id}>
        {strategy.parameters.map((parameter) => {
          const inputId = `backtest-${parameter.key}`
          const errorId = `${inputId}-error`
          const error = errors[parameter.key]

          return (
            <label className="backtest-field" htmlFor={inputId} key={parameter.key}>
              <span>{parameter.label}</span>
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
              {error && <small className="backtest-field-error" id={errorId}>{error}</small>}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}
