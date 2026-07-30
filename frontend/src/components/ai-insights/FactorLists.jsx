import Icon from '../Icon'

function FactorColumn({ title, eyebrow, items, tone }) {
  return (
    <section className={`ai-insights-card ai-insights-factor-card is-${tone}`} aria-labelledby={`ai-insights-${tone}-title`}>
      <div className="ai-insights-card-header">
        <div>
          <p>{eyebrow}</p>
          <h2 id={`ai-insights-${tone}-title`}>{title}</h2>
        </div>
      </div>

      <ul className="ai-insights-factor-list">
        {items.map((item) => (
          <li key={item.id}>
            <span className={`ai-insights-factor-icon is-${item.tone}`} aria-hidden="true">
              <Icon name={item.icon} />
            </span>
            <div>
              <strong>{item.title}</strong>
              <span>{item.description.replace('model agreement', 'forecast consistency')}</span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default function FactorLists({ supportingFactors, riskFactors }) {
  return (
    <div className="ai-insights-factor-grid">
      <FactorColumn
        title="Supporting Factors"
        eyebrow="Positive evidence"
        items={supportingFactors}
        tone="supporting"
      />
      <FactorColumn
        title="Risk Factors"
        eyebrow="Risk warnings"
        items={riskFactors}
        tone="risk"
      />
    </div>
  )
}
