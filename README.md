# AIquant

An AI-assisted investment analysis platform that combines market data, quantitative indicators, portfolio simulation, strategy backtesting, and AI-generated insights.

**[Live Demo](https://aiquant-frontend.onrender.com)**

## Overview

AIquant helps individual investors explore market conditions, evaluate trading strategies, and understand the reasoning behind quantitative signals.

The platform brings market analysis and portfolio tools into one workflow. It combines calculated indicators with natural-language explanations generated through the DeepSeek API.

## Key Features

- **Market Dashboard:** Explore price charts and technical indicators.
- **Market Analysis:** Assess market regimes and evaluate strategy suitability.
- **AI Insights:** Generate analysis and risk explanations using structured market context.
- **Portfolio Simulation:** Manage simulated holdings, transactions, and cash balances.
- **Strategy Backtesting:** Evaluate historical strategy performance through returns and drawdowns.
- **Watchlist:** Save and monitor securities of interest.
- **User Authentication:** Access account-specific features through JWT-based authentication.

## Technology Stack

| Layer | Technologies |
| --- | --- |
| Frontend | React, JavaScript |
| Backend | Python, Django, Django REST Framework |
| Database | PostgreSQL |
| Market Data | Twelve Data API |
| AI Integration | DeepSeek API |
| Authentication | JWT |
| Deployment | Render |

## AI Analysis Workflow

1. Retrieve market data from Twelve Data.
2. Calculate technical indicators and assess market conditions.
3. Assemble relevant metrics and strategy evaluation results into structured context.
4. Submit the context and analysis instructions to the DeepSeek API.
5. Display the generated interpretation and risk explanations alongside quantitative results.

Quantitative calculations are handled by the application. The language model helps explain the supplied results.

## Development and Contributions

This is an individual project covering requirements analysis, system design, frontend and backend implementation, API integration, deployment, and evaluation.

My responsibilities included:

- Defining requirements and prioritizing features.
- Designing application workflows, APIs, and data models.
- Integrating market data and AI-generated explanations.
- Reviewing and modifying implementation code.
- Conducting testing, debugging, and user evaluation.

ChatGPT and Codex supported idea exploration, code generation, debugging, and testing. AI-generated output was reviewed, adapted, and tested before integration. Requirements, architectural decisions, and final validation remained my responsibility.

## Evaluation and Limitations

The project was evaluated through software testing and user tasks with questionnaire feedback.

Current limitations include:

- Mobile usability requires further refinement.
- AI-generated explanations may contain inaccuracies.
- Backtesting results depend on historical data and strategy assumptions.
- Portfolio transactions are simulated; the platform does not execute real brokerage orders.

## Future Development

- Improve mobile layouts and accessibility.
- Expand strategy selection and configuration.
- Add multi-timeframe analysis and watchlist alerts.
- Strengthen account management and recovery features.
