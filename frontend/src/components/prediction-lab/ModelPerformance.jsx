export default function ModelPerformance({ forecast }) {
  if (!forecast.modelPerformance) {
    return <section className="prediction-card prediction-equal-card"><div className="prediction-card-header"><div><p>Historical test</p><h2>Historical Model Performance</h2><span>Not implemented. Real OHLCV is available, but no model has been trained or evaluated.</span></div></div></section>
  }
  const performance = forecast.modelPerformance
  const metrics = [
    ['Accuracy', `${performance.accuracy.toFixed(1)}%`],
    ['Balanced Accuracy', `${performance.balancedAccuracy.toFixed(1)}%`],
    ['Precision', `${performance.precision.toFixed(1)}%`],
    ['Recall', `${performance.recall.toFixed(1)}%`],
    ['F1 Score', `${performance.f1.toFixed(1)}%`],
    ['Macro F1', `${performance.macroF1.toFixed(1)}%`],
    ['Minimum Class Recall', `${performance.minimumClassRecall.toFixed(1)}%`],
    ['ROC-AUC', Number.isFinite(performance.rocAuc) ? performance.rocAuc.toFixed(2) : 'N/A'],
  ]
  const regressionMetrics = performance.regression ? [
    ['MAE', `${(performance.regression.mae * 100).toFixed(2)}%`],
    ['RMSE', `${(performance.regression.rmse * 100).toFixed(2)}%`],
    ['R²', Number.isFinite(performance.regression.r2) ? performance.regression.r2.toFixed(2) : 'N/A'],
    ['Zero-return MAE', Number.isFinite(performance.regression.zero_return_baseline?.mae)
      ? `${(performance.regression.zero_return_baseline.mae * 100).toFixed(2)}%`
      : 'N/A'],
    ['Zero-return RMSE', Number.isFinite(performance.regression.zero_return_baseline?.rmse)
      ? `${(performance.regression.zero_return_baseline.rmse * 100).toFixed(2)}%`
      : 'N/A'],
  ] : []
  const regression = performance.regression

  return (
    <section className="prediction-card prediction-equal-card" aria-labelledby="prediction-performance-title">
      <div className="prediction-card-header">
        <div>
          <p>Independent Test</p>
          <h2 id="prediction-performance-title">Historical Model Performance</h2>
          <span>{forecast.selectedModel ?? forecast.selectedCandidateModel} evaluated for the {forecast.configuration.directionHorizonLabel.toLowerCase()} direction target on {performance.testSamples} untouched Test samples after model and threshold selection.</span>
        </div>
      </div>

      <dl className="prediction-performance-grid">
        {metrics.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>

      {regressionMetrics.length > 0 && (
        <>
          <div className="prediction-card-header"><div><p>Regression independent Test</p><h3>{forecast.regressionModel ?? forecast.selectedRegressionCandidateModel ?? regression.model}</h3><span>Return horizon: {forecast.configuration.returnHorizonLabel}. Candidate selection used purged Walk-Forward Validation only.</span></div></div>
          <dl className="prediction-performance-grid">
            {regressionMetrics.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
          </dl>
          {regression.final_quality_gate?.passed === false && (
            <div className="prediction-card-note">
              <strong>Regression Prediction Unavailable.</strong>
              {regression.final_quality_gate.reasons.map((reason) => <p key={reason}>{reason}</p>)}
            </div>
          )}
          {regression.candidate_models?.length > 0 && (
            <details className="prediction-inline-diagnostics">
              <summary>Regression candidate diagnostics ({regression.candidate_models.length})</summary>
              <dl className="prediction-performance-grid">
                {regression.candidate_models.map((candidate, index) => (
                  <div key={`${candidate.model}-${index}`}>
                    <dt>{candidate.selected ? 'Selected · ' : ''}{candidate.model}</dt>
                    <dd>
                      WF MAE {(candidate.model_metrics.mae * 100).toFixed(2)}% · RMSE {(candidate.model_metrics.rmse * 100).toFixed(2)}%<br />
                      Improving folds {candidate.improving_fold_count}/{candidate.folds.length}
                    </dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
        </>
      )}

      <div className="prediction-baseline-row">
        <div>
          <span>Model Accuracy</span>
          <strong>{performance.accuracy.toFixed(1)}%</strong>
        </div>
        <div>
          <span>Majority Class Baseline</span>
          <strong>{performance.baselineAccuracy.toFixed(1)}%</strong>
        </div>
      </div>
      {performance.independentTestQualityGate?.passed === false && (
        <div className="prediction-card-note">
          <strong>Independent Test quality gate failed.</strong>
          {performance.independentTestQualityGate.reasons.map((reason) => <p key={reason}>{reason}</p>)}
        </div>
      )}

      {performance.walkForwardFolds.length > 0 && (
        <div className="prediction-card-header">
          <div>
            <p>Purged Walk-Forward</p>
            <h3>Fold Diagnostics</h3>
            <span>{performance.walkForwardFolds.length} chronological Validation folds used before the independent Test.</span>
          </div>
        </div>
      )}
      {performance.walkForwardFolds.length > 0 && (
        <dl className="prediction-performance-grid">
          {performance.walkForwardFolds.map((fold) => (
            <div key={fold.fold}>
              <dt>Fold {fold.fold}</dt>
              <dd>
                Train {fold.training_samples} · Validation {fold.validation_samples}<br />
                Actual UP/DOWN {fold.actual_up_count}/{fold.actual_down_count}<br />
                Predicted UP/DOWN {fold.predicted_up_count}/{fold.predicted_down_count}
              </dd>
            </div>
          ))}
        </dl>
      )}
      <p className="prediction-card-note">The independent Test does not participate in model selection, hyperparameter tuning, threshold selection, or classifier refitting.</p>
    </section>
  )
}
