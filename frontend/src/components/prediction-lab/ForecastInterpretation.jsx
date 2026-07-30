import Icon from '../Icon'

export default function ForecastInterpretation({ forecast, onOpenInAIInsights, onNavigate, onOpenMarketAnalysis }) {
  const interpretation = forecast.interpretation
    .replace(`${forecast.selectedModel} produces`, 'This deterministic mock forecast indicates')
    .replace('Model outputs or simulated validation performance', 'Underlying forecast signals')
    .replace('model agreement', 'forecast consistency')

  return (
    <section className="prediction-card prediction-interpretation-card" aria-labelledby="prediction-interpretation-title">
      <div className="prediction-card-header">
        <div>
          <p>Rule-based explanation</p>
          <h2 id="prediction-interpretation-title">Forecast Interpretation</h2>
          <span>Template-generated context for the selected asset and forecast settings.</span>
        </div>
      </div>
      <p>{interpretation}</p>

      <div className="prediction-action-layout">
        <div>
          <strong>Continue the research workflow</strong>
          <span>Review the latest forecast alongside rule-based decision-support evidence.</span>
        </div>
        <div className="prediction-actions" aria-label="Forecast navigation actions">
          <button type="button" className="is-primary" onClick={onOpenInAIInsights}>
            <Icon name="insights" />Open in AI Insights
          </button>
          <button type="button" onClick={onOpenMarketAnalysis}>
            <Icon name="market" />View Market Analysis
          </button>
          <button type="button" onClick={() => onNavigate('strategy-backtesting')}>
            <Icon name="strategy" />Review Backtest
          </button>
        </div>
      </div>
    </section>
  )
}
