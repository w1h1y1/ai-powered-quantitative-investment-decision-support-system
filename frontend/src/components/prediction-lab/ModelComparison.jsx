function formatPercent(value) {
  return Number.isFinite(value) ? `${value.toFixed(1)}%` : 'N/A'
}

export default function ModelComparison({ forecast }) {
  if (!forecast.modelComparison?.length) {
    return <section className="prediction-card prediction-comparison-card"><div className="prediction-card-header"><div><p>Model output</p><h2>Model Comparison</h2><span>Insufficient historical samples to train and compare classification models.</span></div></div></section>
  }
  const forecastWithheld = !forecast.predictionAvailable
  const isAutomaticSelection = forecast.modelSelectionMode === 'automatic'
  const selectionReason = forecast.selectionReason
    ?? 'The selected model has the strongest weighted chronological validation score.'

  return (
    <section className="prediction-card prediction-comparison-card" aria-labelledby="prediction-comparison-title">
      <div className="prediction-card-header">
        <div>
          <p>Chronological validation</p>
          <h2 id="prediction-comparison-title">Model Comparison</h2>
          <span>
            {isAutomaticSelection
              ? 'The candidate is selected only from purged Walk-Forward Validation; the independent Test is evaluated afterward as a publication gate.'
              : 'Model comparison is shown using chronological validation metrics.'}
          </span>
        </div>
      </div>

      <div className="prediction-model-selection-summary">
        <div>
          <span>{forecastWithheld ? 'Selected Research Candidate' : 'Selected Model'}</span>
          <strong>{forecast.selectedModel ?? forecast.selectedCandidateModel ?? 'Unavailable'}</strong>
          <small>{forecastWithheld ? 'Formal forecast withheld by the quality gate' : 'Automatically selected from Walk-Forward Validation'}</small>
        </div>
        <p>{selectionReason}</p>
      </div>

      <div className="prediction-table-wrap">
        <table className="prediction-comparison-table">
          <caption className="sr-only">Classification model chronological validation comparison</caption>
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col">Direction</th>
              <th scope="col">Probability</th>
              <th scope="col">Accuracy</th>
              <th scope="col">Precision</th>
              <th scope="col">Recall</th>
              <th scope="col">F1</th>
              <th scope="col">ROC-AUC</th>
            </tr>
          </thead>
          <tbody>
            {forecast.modelComparison.map((model) => {
              const isSelected = model.selected
              return (
                <tr className={isSelected ? 'is-selected' : undefined} key={model.key}>
                  <td data-label="Model">
                    <span className="prediction-model-name">
                      <strong>{model.label}</strong>
                      {isSelected && <small>Selected</small>}
                    </span>
                  </td>
                  <td data-label="Direction">
                    <span className={`prediction-status is-${forecastWithheld ? 'unavailable' : model.predictedDirection.toLowerCase()}`}>
                      {forecastWithheld ? 'Withheld' : model.predictedDirection}
                    </span>
                  </td>
                  <td data-label="Probability">{forecastWithheld ? 'Withheld' : formatPercent(model.probabilityIncrease)}</td>
                  <td data-label="Accuracy">{formatPercent(model.accuracy)}</td>
                  <td data-label="Precision">{formatPercent(model.precision)}</td>
                  <td data-label="Recall">{formatPercent(model.recall)}</td>
                  <td data-label="F1">{formatPercent(model.f1)}</td>
                  <td data-label="ROC-AUC">{Number.isFinite(model.rocAuc) ? model.rocAuc.toFixed(2) : 'N/A'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="prediction-card-note">Candidate metrics come from purged Walk-Forward Validation. The independent Test is not used to choose the candidate or threshold.</p>
    </section>
  )
}
