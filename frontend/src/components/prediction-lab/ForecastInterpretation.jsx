import Icon from '../Icon'

export default function ForecastInterpretation({ forecast, onOpenInAIInsights, onNavigate, onOpenMarketAnalysis }) {
  if (!forecast.predictionAvailable) {
    return (
      <section className="prediction-card prediction-interpretation-card" aria-labelledby="prediction-interpretation-title">
        <div className="prediction-card-header"><div><p>Prediction status</p><h2 id="prediction-interpretation-title">Forecast Interpretation</h2><span>Real market data is available, but the selected window does not support reliable model training.</span></div></div>
        <p>{forecast.predictionMessage}</p>
        <div className="prediction-action-layout"><div><strong>Continue the research workflow</strong><span>Review the loaded market data in Market Analysis. AI Insights is not given a placeholder prediction.</span></div><div className="prediction-actions"><button type="button" onClick={onOpenMarketAnalysis}><Icon name="market" />View Market Analysis</button><button type="button" onClick={() => onNavigate('strategy-backtesting')}><Icon name="strategy" />Review Backtest</button></div></div>
      </section>
    )
  }
  return (
    <section className="prediction-card prediction-interpretation-card" aria-labelledby="prediction-interpretation-title">
      <div className="prediction-card-header">
        <div>
          <p>Model-based explanation</p>
          <h2 id="prediction-interpretation-title">Forecast Interpretation</h2>
          <span>Summary of the real classification and regression outputs for the selected settings.</span>
        </div>
      </div>
      <p>{forecast.interpretation}</p>

      <div className="prediction-action-layout">
        <div>
          <strong>Continue the research workflow</strong>
          <span>Review the model estimate alongside market data and backtest evidence.</span>
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
