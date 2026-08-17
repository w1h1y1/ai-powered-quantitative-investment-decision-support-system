# System Testing

## Scope

This document covers the **current final system** of the AI Quantitative
Investment Decision Support System:

```text
Market Data
→ Market Analysis / Market Regime
→ Strategy Selection
→ Strategy Evaluation / Backtest
→ Agent Context
→ Investment Agent
```

It records System Test Cases for the user-visible React frontend and the
Django REST API. Results are marked as:

- **Pass (Automated)** — proven by the backend/frontend automated test suite.
- **Pass (Previously Verified)** — verified during development against the
  real API / real DeepSeek on 2026-08.
- **Pending Manual Verification** — page-level or end-to-end scenario that has
  not yet been executed by a human in the final build.

## Testing Environment

- Backend: Django 6.0.6 / Django REST Framework 3.17.1 / PostgreSQL (local)
- Frontend: React 19 + Vite 7
- Market data provider: Twelve Data (cached in the project database)
- LLM provider: DeepSeek (`deepseek-chat`)
- Automated tests run **without any external API** (Twelve Data and DeepSeek
  are mocked/patched).
- Manual verification used a local Django server plus a real DeepSeek key.

## Test Case Matrix

### Auth

| ID | Module | Test Scenario | Preconditions | Steps | Expected Result | Test Type | Result |
| -- | ------ | ------------- | ------------- | ----- | --------------- | --------- | ------ |
| ST-AU-01 | Auth | Login with valid credentials | Registered user exists | Open `/login` → enter credentials → submit | Authenticated and redirected to Dashboard; session cookie set | Functional | Pass (Automated) |
| ST-AU-02 | Auth | Register a new account | Username/email not taken | Open `/register` → fill form → submit | Account created and user authenticated | Functional | Pass (Automated) |
| ST-AU-03 | Auth | Unauthenticated API access rejected | No session cookie | Call any `/api/...` endpoint without auth | Request rejected (401/403); no data returned | Negative | Pass (Automated) |
| ST-AU-04 | Auth | Logout returns to login page | User logged in | Click logout in header | Session cleared; redirected to `/login` | Functional | Pending Manual Verification |

### Dashboard / Market Data

| ID | Module | Test Scenario | Preconditions | Steps | Expected Result | Test Type | Result |
| -- | ------ | ------------- | ------------- | ----- | --------------- | --------- | ------ |
| ST-DB-01 | Dashboard | Dashboard loads real market summary | User logged in; API reachable | Open Dashboard | Market summary cards load from `/api/market-data/summary/` | Functional | Pending Manual Verification |
| ST-DB-02 | Dashboard | Price chart renders and range switch works | Dashboard loaded | Switch 1D/1W/1M/3M/6M/1Y/Custom | Chart and labels update to the selected range | Functional | Pending Manual Verification |
| ST-DB-03 | Dashboard | Technical indicators display | Dashboard loaded | View RSI/MACD/MA/volatility panel | Indicator values and signals render from real data | Functional | Pending Manual Verification |
| ST-DB-04 | Market Data | Sub-API failure does not crash the page | Provider can fail | Simulate summary/quote/daily API failure | Failed module shows isolated error; other modules keep working | Integration | Pass (Automated) |
| ST-DB-05 | Market Data | Invalid custom date range rejected | Custom range selected | Enter end before start / invalid dates | Clear validation error, no request sent | Negative | Pass (Automated) |
| ST-DB-06 | Market Data | Unknown symbol / unsupported interval rejected | API request made | Query daily data with unknown security or bad interval | HTTP 4xx with clear error message | Negative | Pass (Automated) |
| ST-DB-07 | Market Data | Returned data matches requested range/interval | Market data API called | Request range + interval; inspect metadata | `first_datetime`/`last_datetime`/interval consistent with request | Consistency | Pass (Automated) |

### Watchlist

| ID | Module | Test Scenario | Preconditions | Steps | Expected Result | Test Type | Result |
| -- | ------ | ------------- | ------------- | ----- | --------------- | --------- | ------ |
| ST-WL-01 | Watchlist | Add stock via remote search | Search box available | Type symbol → select remote result → add | Stock appears in watchlist with quote data | Functional | Pending Manual Verification |
| ST-WL-02 | Watchlist | Delete stock | Stock exists in watchlist | Click delete on item | Item removed; confirmation feedback shown | Functional | Pending Manual Verification |
| ST-WL-03 | Watchlist | One-character query does not hit remote provider | Search box available | Type a single character | No remote search call; local results only | Negative | Pass (Automated) |
| ST-WL-04 | Watchlist | Item click opens Market Analysis for that symbol | Watchlist item exists | Click item / "View analysis" | Market Analysis page opens with the same symbol selected | Integration | Pending Manual Verification |
| ST-WL-05 | Watchlist | Quotes refresh with cache/stale handling | Watchlist loaded | Force refresh / wait TTL | Fresh quotes from provider; cached/stale fallback flagged | Consistency | Pass (Automated) |

### Portfolio

| ID | Module | Test Scenario | Preconditions | Steps | Expected Result | Test Type | Result |
| -- | ------ | ------------- | ------------- | ----- | --------------- | --------- | ------ |
| ST-PF-01 | Portfolio | Buy success | Enough liquidity | Select security → enter quantity/price → Buy | Transaction created; holding increases; liquidity decreases | Functional | Pass (Automated) |
| ST-PF-02 | Portfolio | Insufficient liquidity rejected | Cash below required amount | Attempt buy above available funds | Transaction rejected; all changes rolled back | Negative | Pass (Automated) |
| ST-PF-03 | Portfolio | Sell success | Holding exists | Sell quantity ≤ holding | Transaction created; holding decreases; proceeds added | Functional | Pass (Automated) |
| ST-PF-04 | Portfolio | Sell quantity cannot exceed holding | Holding exists | Sell quantity > holding | Rejected; holding and balance preserved | Negative | Pass (Automated) |
| ST-PF-05 | Portfolio | Sell without holding rejected | No holding | Attempt sell | Rejected; no transaction created | Negative | Pass (Automated) |
| ST-PF-06 | Portfolio | Sell dialog shows only real holdings; WAC consistent | Portfolio with holdings | Open Sell dialog; check quantities and average cost | Dropdown lists only held securities; average cost matches transactions | Consistency | Pending Manual Verification |
| ST-PF-07 | Portfolio | Transaction history and filters | Transactions exist | Open history; switch Today/7D/YTD/Quarter | Records match selected period; pagination works | Integration | Pass (Automated) |
| ST-PF-08 | Portfolio | Summary totals and remaining liquidity consistent | Trades executed | View portfolio summary | Holdings value + available funds = total; realized P/L correct | Integration | Pass (Automated) |
| ST-PF-09 | Portfolio | UI buy/sell dialog flow | User logged in | Use Buy and Sell dialogs end-to-end | Transaction appears in history; holdings/liquidity update in UI | Functional | Pending Manual Verification |
| ST-PF-10 | Portfolio | User data isolation | Two users exist | User A trades; inspect User B | No cross-user transactions/holdings/summary leakage | Consistency | Pass (Automated) |

### Market Analysis

| ID | Module | Test Scenario | Preconditions | Steps | Expected Result | Test Type | Result |
| -- | ------ | ------------- | ------------- | ----- | --------------- | --------- | ------ |
| ST-MA-01 | Market Analysis | Market Regime loads for AAPL/JPM/XOM | API reachable; data cached | Open Market Analysis for each symbol | Regime + confidence + explanation returned for each | Integration | Pass (Previously Verified) |
| ST-MA-02 | Market Analysis | Symbol switch leaves no old regime data | Regime loaded for one symbol | Switch JPM → XOM | Page shows XOM regime only; no JPM residue | Consistency | Pass (Previously Verified) |
| ST-MA-03 | Market Analysis | AAPL Risk-Off → Evaluation Not Applicable | AAPL context available | Select AAPL; view Strategy Evaluation | `risk_off=true`, `allow_new_long=false`, status `not_applicable` with reason | Integration | Pass (Previously Verified) |
| ST-MA-04 | Market Analysis | JPM/XOM Mean Reversion evaluation | Context available | Select JPM/XOM; view Strategy Evaluation | `mean_reversion` + completed metrics displayed | Integration | Pass (Previously Verified) |
| ST-MA-05 | Market Analysis | Symbol switch clears old evaluation | Evaluation loaded for one symbol | Switch to another symbol | Old evaluation cleared while loading; new one appears | Consistency | Pass (Previously Verified) |
| ST-MA-06 | Market Analysis | Stale response cannot overwrite current symbol | Slow network possible | Rapidly switch AAPL → JPM → XOM | Slow old response ignored; page stays on latest symbol | Negative | Pass (Previously Verified) |
| ST-MA-07 | Market Analysis | Strategy Evaluation API failure isolated | API can fail | Force evaluation request failure | Evaluation panel shows Unavailable; regime/charts unaffected | Negative | Pass (Previously Verified) |
| ST-MA-08 | Market Analysis | Market Regime unavailable is explicit, not a 500 | Insufficient history / provider issue | Request regime for affected symbol | Explicit unavailable state with reason; HTTP 200 contract | Negative | Pass (Automated) |
| ST-MA-09 | Market Analysis | Unknown symbol returns clear validation error | API request made | Query unknown symbol | HTTP 400 with `Security is not available.` | Negative | Pass (Automated) |
| ST-MA-10 | Market Analysis | Charts render and range switching works | Market data loaded | Switch ranges; zoom/pan price, RSI, MACD, volume | Charts update to selected range/interval | Functional | Pending Manual Verification |

### Backtest / Strategy Evaluation

| ID | Module | Test Scenario | Preconditions | Steps | Expected Result | Test Type | Result |
| -- | ------ | ------------- | ------------- | ----- | --------------- | --------- | ------ |
| ST-BT-01 | Backtest | Run backtest produces results | Asset + dates valid | Set params → Run | Equity curve, drawdown, exposure, metrics returned | Functional | Pass (Automated) |
| ST-BT-02 | Backtest | Parameter changes alter results deterministically | Valid config | Change risk/MA params; run twice | Results differ by params; repeated runs identical | Functional | Pass (Automated) |
| ST-BT-03 | Backtest | Requested vs actual window consistent | Backtest run | Inspect data_source dates | Actual start/end inside requested window | Consistency | Pass (Automated) |
| ST-BT-04 | Backtest | Invalid parameters rejected | API request made | Submit fast ≥ slow MA / out-of-range risk | HTTP 400 with field errors | Negative | Pass (Automated) |
| ST-BT-05 | Backtest | Insufficient history returns clear error | Short history | Run backtest on insufficient data | Clear 400 error naming asset/benchmark coverage | Negative | Pass (Automated) |
| ST-BT-06 | Backtest | Provider rate limit / failure handled | Provider can fail | Trigger 429/503 | Mapped to 429/503; no crash | Negative | Pass (Automated) |
| ST-BT-07 | Backtest | Backtest UI form + results render | User logged in | Fill form → Run → view results | Config, results, charts render correctly | Functional | Pending Manual Verification |
| ST-BT-08 | Backtest | History persistence, reopen and delete | Previous runs exist | Reopen/delete a saved run | History restored from local storage; delete works | Functional | Pending Manual Verification |
| ST-BT-09 | Strategy Evaluation | Server-selected strategy evaluation for current symbol | Symbol valid | POST `/api/strategy-evaluation/` `{"symbol": ...}` | Server runs Regime → Selection → Evaluation; client cannot override strategy | Integration | Pass (Previously Verified) |

### Investment Agent

The Investment Agent has **no frontend page yet**; it is verified at API level
(`POST /api/investment-agent/`, body `{"symbol": "..."}`).

| ID | Module | Test Scenario | Preconditions | Steps | Expected Result | Test Type | Result |
| -- | ------ | ------------- | ------------- | ----- | --------------- | --------- | ------ |
| ST-AG-01 | Investment Agent | JPM full success path | Context available; DeepSeek key set | POST `/api/investment-agent/` for JPM | HTTP 200, `analysis_available=true`, `analysis_version=investment_agent_analysis_v1` | Integration | Pass (Previously Verified) |
| ST-AG-02 | Investment Agent | XOM full success path | Context available | POST for XOM | Structured analysis consistent with XOM context | Integration | Pass (Previously Verified) |
| ST-AG-03 | Investment Agent | AAPL full success path | Context available | POST for AAPL | Risk-Off / Not Applicable explained correctly | Integration | Pass (Previously Verified) |
| ST-AG-04 | Investment Agent | No cross-symbol contamination | Previous calls made | POST JPM → XOM → AAPL sequentially | Each response only contains its own symbol/context | Consistency | Pass (Previously Verified) |
| ST-AG-05 | Investment Agent | Strategy/risk/evaluation facts preserved | Valid context | Compare analysis to context | LLM explains deterministic facts; never changes strategy/risk fields | Consistency | Pass (Previously Verified) |
| ST-AG-06 | Investment Agent | Provider failure fallback | Mock LLM failure | Simulate timeout/5xx/network | `analysis_available=false`, `failure_reason` set, context preserved | Negative | Pass (Automated) |
| ST-AG-07 | Investment Agent | Invalid JSON fallback | Mock LLM output | Return non-JSON | Falls back with `invalid_json`/`invalid_response` | Negative | Pass (Automated) |
| ST-AG-08 | Investment Agent | Schema invalid fallback | Mock LLM output | Return JSON missing field / wrong type | `failure_reason=schema_invalid`; repair retry max once | Negative | Pass (Automated) |
| ST-AG-09 | Investment Agent | API key missing fallback | No key configured | Call endpoint | `api_key_missing` fallback; deterministic context still returned | Negative | Pass (Automated) |
| ST-AG-10 | Investment Agent | Units: percentage_points vs decimal_fraction | Completed evaluation | Inspect analysis of JPM/XOM | `0.566941 percentage_points` explained as ≈0.57%; returns not ×100 | Consistency | Pass (Previously Verified) |
| ST-AG-11 | Investment Agent | No unauthorized BUY/SELL or invented numbers | Valid analysis | Audit analysis output | No trade instructions; every number traceable to context | Negative | Pass (Previously Verified) |

## Results Summary

### Overall

| Metric | Count |
| ------ | ----: |
| Total test cases | 56 |
| Passed / Previously Verified | 44 |
| Pending Manual Verification | 12 |
| Failed | 0 |

### By test type

| Test Type | Count |
| --------- | ----: |
| Functional | 16 |
| Negative | 19 |
| Integration | 11 |
| Consistency | 10 |

### By module

| Module | Total | Passed | Pending | Failed |
| ------ | ----: | -----: | ------: | -----: |
| Auth | 4 | 3 | 1 | 0 |
| Dashboard / Market Data | 7 | 4 | 3 | 0 |
| Watchlist | 5 | 2 | 3 | 0 |
| Portfolio | 10 | 8 | 2 | 0 |
| Market Analysis | 10 | 9 | 1 | 0 |
| Backtest / Strategy Evaluation | 9 | 7 | 2 | 0 |
| Investment Agent | 11 | 11 | 0 | 0 |
| **Total** | **56** | **44** | **12** | **0** |

## Known Limitations

- **External market data dependency**: prices come from Twelve Data; free-tier
  rate limits and provider availability can cause 429/503, handled through
  caching and stale-cache fallback.
- **LLM provider dependency**: the Investment Agent explanation layer depends
  on DeepSeek. When the provider fails, the system falls back to the
  deterministic Agent Context with `analysis_available=false`.
- **Sector context coverage**: sector mapping is a curated list; unknown
  symbols degrade to `sector_context_available=false` and no sector regime is
  guessed.
- **Data freshness**: `as_of_date` comes from market data, not the browser
  clock; results reflect the latest cached/refreshed market date.
- **Decision support, not execution**: Backtest/Strategy Evaluation are
  historical simulations; the Investment Agent never places orders, modifies
  the portfolio, or provides trade execution.
- **Investment Agent has no frontend page yet**; it is currently verified at
  the API level.
- **AI Insights page is a placeholder** (rule-based mock content) and is not
  part of the current core evaluation.

## Legacy Prediction Lab Note

The `prediction/` module (Prediction Lab / Machine Learning) was implemented
and tested during development (~110 tests) but was **not retained as a core
feature** of the final system due to model stability, baseline comparison, and
cross-stock generalization concerns.

- The legacy tests are kept as a historical development record and are **not
  counted** as evidence for the final Investment Agent system.
- Current core system tests are defined by the modules in this document and by
  the backend automated suite for Market Data, Market Regime, Strategy
  Selection, Strategy Evaluation/Backtest, Agent Context, and Investment Agent.
