import { buildPortfolioSummaryCards } from './portfolioSummaryModel'

export default function PortfolioOverview({ summary }) {
  const cards = buildPortfolioSummaryCards(summary)

  return (
    <section className="portfolio-summary-section" aria-labelledby="portfolio-summary-title">
      <div className="portfolio-section-heading">
        <div>
          <p>Account overview</p>
          <h2 id="portfolio-summary-title">Portfolio Summary</h2>
        </div>
      </div>

      <div className="portfolio-summary-grid">
        {cards.map((card) => (
          <article className={`portfolio-summary-card ${card.tone ?? ''}`.trim()} key={card.label}>
            <span>{card.label}</span>
            <strong>{card.value}</strong>
            <small>{card.detail}</small>
          </article>
        ))}
      </div>
    </section>
  )
}
