export default function ModelPerformance({ forecast }) {
  const performance = forecast.modelPerformance
  const metrics = [
    ['Accuracy', `${performance.accuracy}%`],
    ['Precision', `${performance.precision}%`],
    ['Recall', `${performance.recall}%`],
    ['F1 Score', `${performance.f1}%`],
    ['ROC-AUC', performance.rocAuc.toFixed(2)],
  ]

  return (
    <section className="prediction-card prediction-equal-card" aria-labelledby="prediction-performance-title">
      <div className="prediction-card-header">
        <div>
          <p>Simulated historical test</p>
          <h2 id="prediction-performance-title">Historical Model Performance</h2>
          <span>{forecast.selectedModel} evaluated over the selected mock window.</span>
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

      <div className="prediction-baseline-row">
        <div>
          <span>Model Accuracy</span>
          <strong>{performance.accuracy}%</strong>
        </div>
        <div>
          <span>Majority Class Baseline</span>
          <strong>{performance.baselineAccuracy}%</strong>
        </div>
      </div>
      <p className="prediction-card-note">Performance metrics describe simulated historical test results and do not guarantee future accuracy.</p>
    </section>
  )
}

