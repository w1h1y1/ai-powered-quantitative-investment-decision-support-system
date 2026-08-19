# Checkpoint 4 — Technical Testing & Evaluation Report

**Project:** AI-Powered Quantitative Investment Decision Support System
**Date:** 2026-08-19
**Scope:** Formal Checkpoint 4 testing: Unit, Integration, API, Regression and
Error-Handling testing of the current core system.
**Test environment:** Django 6.0.6 / DRF 3.17.1 / PostgreSQL (local),
React 19 + Vite 7 (Node 24), Python 3.13.5.

---

## A. Executive Summary

This checkpoint validated the current production build of the investment
decision-support system without modifying any business code. All changes made
during this round are test-only additions/assertions. The existing automated
baseline was run first (backend 619 tests, frontend 201 tests), then a small
number of high-value tests were added to close gaps in the Checkpoint 4
requirements, and the complete suites were re-run.

**Final results:**

- Backend: **624 tests run, 624 passed, 0 failed, 0 errors, 0 skipped**
  (613.8 s). This includes 514 core-system tests and 110 legacy Prediction-Lab
  tests that remain green but are not counted as core evidence.
- Frontend: **202 tests run, 202 passed, 0 failed, 0 skipped** (3.1 s).
- **No blocking defects found.** No business code was changed. No secrets were
  printed, logged, or committed. No live external API call was made.

The system currently shows no known automated-test regression, and all
previously fixed dashboard/security/search/backtest/authentication issues are
now covered by automated regression tests. The system is considered suitable
to proceed to the Task Sheet + Microsoft Forms User Evaluation stage.

## B. Test Result Table

All figures below are from the actual final test runs
(`manage.py test` for the backend, `npm test` for the frontend).

| Area | Test Type | Total | Passed | Failed | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| Authentication | Unit/API | 19 | 19 | 0 | Register, duplicate user/email, weak password, JWT login/refresh/expiry, 401 on protected APIs |
| Dashboard / Market Data | Unit/API/Integration | 79 | 79 | 0 | Security search/resolve, OHLCV schema, quotes, summary, symbol-switch consistency, empty response, provider errors |
| Watchlist | Unit/API | 20 | 20 | 0 | Add/duplicate/remove/list, remote-resolved symbols, user isolation, no portfolio side-effects |
| Portfolio | Unit/Integration | 138 | 138 | 0 | Buy/sell/dividend validation, liquidity, WAC, realized/unrealized P/L, funding, performance, user isolation |
| Backtest / Strategy Evaluation | Unit/Integration/API | 97 | 97 | 0 | Symbol-specific data, benchmark propagation (SPY/QQQ), parameters, deterministic reruns, schema, error paths |
| Market Regime | Unit/API | 24 | 24 | 0 | Legal regime values, confidence, unavailable state, 429/503 mapping, resolve→regime for JPM/XOM |
| Agent Context | Unit/API | 63 | 63 | 0 | `agent_context_v1` schema, units, multi-symbol (AAPL/JPM/XOM), no hallucination, degraded modules |
| Investment Agent | Unit/Integration | 74 | 74 | 0 | Success path, invalid JSON, schema violation, provider failure matrix, grounding constraints, no secrets |
| **Core backend total** | **Unit/API/Integration** | **514** | **514** | **0** | |
| Frontend | Unit/Component | 202 | 202 | 0 | Symbol selection state, search, loading/error fallback, API failure isolation, trade validation |
| Legacy Prediction Lab (excluded from core evidence) | Unit | 110 | 110 | 0 | Historical development record only |
| **Grand total** | | **826** | **826** | **0** | |

## C. Failed Tests / Defects

There are **no failing tests and no recorded application defects** in this
round. All 826 automated tests pass.

Non-blocking observations (no code change required):

| Observation | Module | Severity | Recommended action |
| --- | --- | --- | --- |
| `sklearn` `FutureWarning: 'penalty' was deprecated` during legacy Prediction-Lab tests | prediction (legacy) | Low | Pin/update sklearn API in a future maintenance round; irrelevant to the core system evidence |
| `joblib` warns "found 0 physical cores" on this machine | prediction (legacy) | Low | Environment-only warning; set `LOKY_MAX_CPU_COUNT` if silencing is desired |
| `numpy ks_2samp: Exact calculation unsuccessful` runtime warning | prediction (legacy) | Low | Statistical method fallback in library; non-fatal |

## D. Added Tests (this round)

| File | Test / change | Purpose |
| --- | --- | --- |
| `market/tests_market_data.py` | `RemoteResolvedMarketDataIntegrationTests.test_remote_resolved_xom_serves_xom_ohlcv` | Regression: a remotely resolved XOM security immediately serves XOM K-line data from `/api/market-data/daily/`; response symbol matches the resolved security |
| `market/tests_market_data.py` | `RemoteResolvedMarketDataIntegrationTests.test_remote_resolved_qqq_serves_qqq_ohlcv` | Regression: QQQ (remote ETF) resolves and loads its own OHLCV data |
| `market/tests_market_data.py` | `MarketDataApiTests.test_market_data_api_returns_empty_ohlcv_contract` | API contract for an empty OHLCV response: HTTP 200, empty arrays, zero counts, no crash |
| `watchlist/tests_api.py` | `WatchlistApiTests.test_add_symbol_does_not_modify_portfolio_state` | Watchlist add operation leaves portfolio funds, holdings, transactions and cash flows unchanged |
| `agent/tests/test_agent_context_api.py` | `AgentContextApiTests.test_jpm_and_xom_resolve_to_their_own_contexts` | `agent_context_v1` multi-symbol correctness: JPM and XOM resolve to their own contexts; request symbol equals context symbol |
| `frontend/src/components/dashboard/dashboardSecurityModel.test.js` | "switching from SPY to remote XOM requests XOM data and rejects stale SPY responses" | Frontend regression guard: after switching SPY→XOM, the market-data request uses XOM's id and stale SPY responses are rejected |
| `backtest/tests.py` | Strengthened `test_real_daily_prices_drive_hybrid_and_all_three_comparisons` | Response schema now explicitly asserts `swing_win_rate`, `executed_order_count`, `total_return`, `maximum_drawdown`, `annualized_volatility` |

All new tests follow Given/When/Then style and assert business behavior rather
than implementation details.

## E. Regression Results

Previously fixed issues re-verified by the automated suites this round:

| # | Previously fixed issue | Automated coverage | Result |
| --- | --- | --- | --- |
| 1 | Dashboard no longer locks to SPY | `dashboardHoldingsSource.test.js`, `dashboardSecurityModel.test.js` (selection resolution, empty-state arbitrary search) | Pass |
| 2 | QQQ loads normally | New `test_remote_resolved_qqq_serves_qqq_ohlcv`; market data API tests | Pass |
| 3 | XOM (remote security) loads K-line | New `test_remote_resolved_xom_serves_xom_ohlcv`; `test_resolved_xom_uses_energy_sector_context` | Pass |
| 4 | Security search not limited to Popular | `test_symbol_search_merges_local_and_remote_results`, `test_symbol_search_filters_unsupported_remote_assets_and_labels_source`, resolve tests; frontend `securitySearchModel.test.js` | Pass |
| 5 | Portfolio security selector uses real user data | `normalizeHoldingsToDashboardSecurities` frontend tests; `test_user_a_only_receives_user_a_portfolio_and_holdings` | Pass |
| 6 | Sell only shows real holdings | Frontend `prevents SELL quantity above the current available quantity`, `keeps SELL strict`; backend `test_sell_without_holding_fails...`, `test_sell_more_than_existing_holding_fails...` | Pass |
| 7 | Backtest symbol matches selected security | `test_backtest_api_propagates_asset_and_benchmark_separately`, `test_each_selected_symbol_fills_its_own_warmup_history`, `test_asset_execution_and_pl_use_asset_prices_only` | Pass |
| 8 | Benchmark parameter is not a dead field | `test_backtest_api_propagates_selected_qqq_benchmark`, `test_bull_vs_bear_benchmark_changes_core_decision_path`, `test_bear_benchmark_prevents_core_entry_through_api` | Pass |
| 9 | Market Regime API failure does not crash Market Analysis | Frontend `marketAnalysisErrorIsolation.test.js`, `marketRegimeModel.test.js`; backend 429/503 mapping tests | Pass |
| 10 | Agent analysis uses different context per symbol | `test_agent_pipeline` (AAPL→JPM no leakage), `test_request_isolation.py`, new JPM/XOM context test | Pass |
| 11 | Authentication still works after deployment fixes | `accounts/tests.py` (JWT register/login/refresh/expired/invalid, protected endpoints), frontend `authApiProductionFlow.test.js` | Pass |

## F. External Dependency Testing

**Twelve Data (market data):** All automated tests mock the provider.
`FakeTwelveDataClient` replaces the HTTP client in service-level tests, and
`unittest.mock.patch` replaces `market.services.search_security_symbols`,
`market.views.get_security_daily_market_data`, quote and summary services at
API level. Cache behavior (fresh hit, TTL, stale fallback, rate-limit
preservation) is verified with the Django cache and `SecurityDailyPrice` DB
fixtures, so no real API quota is consumed.

**DeepSeek (LLM):** All automated tests mock the provider through injected
fakes in `agent/tests/fakes.py` (valid structured responses, invalid JSON,
schema violations, timeouts, HTTP 429/401/5xx, network errors, missing API
key). The real `deepseek_provider` HTTP mapping is tested with mocked
requests. The tests verify the full pipeline `symbol → agent_context_v1 →
prompt → provider → JSON parsing → schema validation →
investment_agent_analysis_v1` without real calls.

**Live smoke test:** **Not executed.** The repository has no dedicated live
smoke-test mechanism in the current build, and the instructions for this
checkpoint prohibit adding new paid external API calls. The `system_testing.md`
document already records real-API manual verification from development
("Pass (Previously Verified)" rows). If a one-time live smoke test is desired
for the dissertation appendix, it should be run manually with the developer's
real keys and labelled explicitly as an external integration test.

**Why this approach:** deterministic, repeatable, fast, zero cost, zero rate
limit exposure, and it never prints or stores real API keys or database
credentials.

## G. Dissertation Evidence

### Testing methodology

This project applies a layered automated testing methodology across the
backend and frontend. Backend testing uses Django's test runner with
`APITestCase`/`TestCase` and covers unit (indicator calculations, strategy
rules, schema validation, portfolio accounting), API (endpoint contracts,
authentication, permission isolation, error status codes), and integration
(remote security resolution flowing into market data, market regime, backtest,
agent context and investment agent) layers. External providers (Twelve Data
and DeepSeek) are always mocked or patched at the service boundary so tests
are deterministic, quota-free and repeatable, while provider failure modes
(rate limit, unavailability, invalid JSON, schema violation, timeout) are
exercised explicitly. Frontend testing uses Node's built-in test runner on
pure model/service modules plus source-level component contract checks,
covering symbol selection state, stale-response guards, loading/error
fallbacks, trade validation and module-level failure isolation. All
tests assert observable business behaviour (status codes, payload fields,
symbol consistency, accounting invariants) rather than implementation details.

### Key findings

- 826/826 automated tests pass (514 core backend + 202 frontend + 110 legacy
  Prediction-Lab tests excluded from core evidence); 0 failures, 0 skipped.
- Remote security resolution is symbol-consistent end-to-end: resolving XOM or
  QQQ creates the security and the OHLCV endpoint returns that security's own
  data — the previously fixed "arbitrary dashboard security search" flow is
  now protected by regression tests.
- Symbol switching cannot leak data: the frontend builds market-data requests
  from the selected security id and rejects stale responses for any other
  security, range or interval.
- Portfolio accounting invariants hold under automated test: insufficient
  liquidity, over-sell, zero-quantity, fee rules, weighted-average cost,
  realized/unrealized P/L, and strict user isolation all pass.
- Backtest parameters and benchmark selection genuinely enter the strategy
  engine; benchmark changes alter the regime decision path (e.g., bear SPY
  blocks Core entry) while repeated identical runs are deterministic.
- The deterministic quantitative layer is authoritative: Market Regime is
  never generated by the LLM, and the LLM layer cannot override
  Django-controlled facts (symbol, regime, strategy, risk constraints);
  invalid or contradictory LLM output falls back safely instead of fabricating
  analysis.
- Failure isolation is verified: Market Regime / DeepSeek / market-data
  failures produce explicit 429/503 or unavailable states without crashing the
  Dashboard or Market Analysis workflows.

### Limitations

Automated testing cannot fully cover: subjective usability and visual/UX
quality of the React pages, the financial usefulness or trustworthiness of the
analyses from a user perspective, real-world end-to-end user experience across
different browsers/devices, and long-term reliability of external providers
(Twelve Data free-tier rate limits, DeepSeek availability). These aspects are
deferred to the planned **Task Sheet + Microsoft Forms User Survey**
evaluation, where human participants evaluate task completion, perceived
usefulness, clarity, and trust. Additionally, a single controlled live smoke
test with real provider keys remains recommended as supplementary external
integration evidence before final submission.

---

## Conclusion

### 1. Overall technical testing verdict

**PASS** — all 826 automated tests pass with zero failures, and no
application defects were identified in this round.

### 2. Blocking issues before User Evaluation

**No.** There are no critical or high-severity defects blocking user
evaluation.

### 3. Is the system ready for Task Sheet + Microsoft Forms User Evaluation?

**Yes.** The core workflows (authentication, security search, dashboard,
watchlist, portfolio, backtest, market regime, strategy evaluation, agent
context, investment agent) are stable under automated tests and ready for
human task-based evaluation. Note that 12 manual system-test scenarios in
`system_testing.md` remain "Pending Manual Verification" and can be executed
during the Task Sheet sessions.

### 4. Recommended next 3 steps

1. **Execute the Task Sheet sessions**, using the pending manual scenarios in
   `system_testing.md` as the basis, and record results for the dissertation
   evaluation chapter.
2. **Run the Microsoft Forms User Survey** to capture subjective usability,
   perceived usefulness, clarity and trust metrics that automated tests cannot
   measure.
3. **Perform one controlled live smoke test** (Twelve Data + DeepSeek) with
   real keys, labelled as an external integration test, and optionally add a
   CI-friendly live-smoke command so provider integration evidence can be
   reproduced before submission.

---

## Evidence artifacts

- `checkpoint4_backend_baseline.log` — baseline backend run (619 tests OK)
- `checkpoint4_backend_final.log` — final backend run (624 tests OK)
- `checkpoint4_frontend_final.log` — final frontend run (202 tests OK)
- `system_testing.md` — system test matrix incl. manual-verification status
