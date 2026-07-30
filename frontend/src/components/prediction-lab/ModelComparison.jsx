function formatSignedPercent(value) {
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}

export default function ModelComparison({ forecast }) {
  const isAutomaticSelection = forecast.modelSelectionMode === 'automatic'
  const selectionReason = forecast.selectionReason
    ?? 'This saved forecast uses the demo model recorded when it was originally generated.'

  return (
    <section className="prediction-card prediction-comparison-card" aria-labelledby="prediction-comparison-title">
      <div className="prediction-card-header">
        <div>
          <p>Simulated model outputs</p>
          <h2 id="prediction-comparison-title">Model Comparison</h2>
          <span>
            {isAutomaticSelection
              ? 'The system automatically selects a model using simulated validation performance. Model comparison is shown for transparency.'
              : 'This saved forecast retains its original demo model selection. Model comparison is shown for transparency.'}
          </span>
        </div>
      </div>

      <div className="prediction-model-selection-summary">
        <div>
          <span>Selected Model</span>
          <strong>{forecast.selectedModel}</strong>
          <small>{isAutomaticSelection ? 'Automatically selected demo model' : 'Saved demo model'}</small>
        </div>
        <p>{selectionReason}</p>
      </div>

      <div className="prediction-table-wrap">
        <table className="prediction-comparison-table">
          <caption className="sr-only">Simulated prediction model comparison</caption>
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col">Direction</th>
              <th scope="col">Probability</th>
              <th scope="col">Expected Return</th>
              <th scope="col">Confidence</th>
              <th scope="col">Test Accuracy</th>
              <th scope="col">ROC-AUC</th>
              <th scope="col">Stability</th>
            </tr>
          </thead>
          <tbody>
            {forecast.modelComparison.map((model) => {
              const isSelected = model.key === forecast.configuration.model
              return (
                <tr className={isSelected ? 'is-selected' : undefined} key={model.key}>
                  <td data-label="Model">
                    <span className="prediction-model-name">
                      <strong>{model.label}</strong>
                      {isSelected && <small>Selected</small>}
                    </span>
                  </td>
                  <td data-label="Direction">
                    <span className={`prediction-status is-${model.predictedDirection.toLowerCase()}`}>
                      {model.predictedDirection}
                    </span>
                  </td>
                  <td data-label="Probability">{model.probabilityIncrease}%</td>
                  <td data-label="Expected Return">{formatSignedPercent(model.expectedReturn)}</td>
                  <td data-label="Confidence">{model.confidence}</td>
                  <td data-label="Test Accuracy">{model.accuracy}%</td>
                  <td data-label="ROC-AUC">{model.rocAuc.toFixed(2)}</td>
                  <td data-label="Stability">{Number.isFinite(model.stability) ? `${model.stability}%` : 'Not recorded'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="prediction-card-note">Model performance is based on simulated test results in the current demo.</p>
    </section>
  )
}
