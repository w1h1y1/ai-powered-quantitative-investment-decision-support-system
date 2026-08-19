# Checkpoint 4 — Dashboard Security Search: Full Audit & Diagnostic Report

**Date:** 2026-08-19
**Scope:** Complete data-flow and state-management audit of the Dashboard
Security Search (not a patch for a single symbol). No business logic was
changed; this round only touched one UI string and test files.

---

## 1. Real Search Architecture (verified call chain)

```
Search input (onChange)
  -> handleSecuritySearchQueryChange        frontend/src/components/dashboard/DashboardContent.jsx
  -> securitySearch state slice (query/results/isSearching/hasSearched/error/detail/notice)

Search button (onClick) == Enter (onKeyDown) -> onSearch() -> runDashboardSearch
  (single handler; button type="button"; no <form>, no navigation)

runDashboardSearch                           DashboardContent.jsx
  -> securityApi.search(query)               frontend/src/services/securityApi.js
  -> GET /api/securities/search/?q=...       market/views.py SecurityViewSet.search
  -> search_security_symbols()               market/services.py
       |-> get_local_security_search_results (SQL icontains symbol/name/exchange/mic_code)
       |-> TwelveDataClient.symbol_search()  market/twelve_data.py
       |-> merge + serialize                 build_security_search_payload / serialize_security_search_result
  -> resolveDashboardSearch                  dashboardSearchModel.js
       |-> mergeSecuritySearchOptions        security/securitySearchModel.js (local+remote dedupe)
  -> results rendered                        DashboardSecuritySearch.jsx (Local/Remote badge)

user clicks result -> selectSecuritySearchResult   DashboardContent.jsx
  local (id set)  -> updateSelectedSecurity(id)
  remote (id null)-> securityApi.resolve(...)      POST /api/securities/resolve/
                     -> SecurityViewSet.resolve    -> resolve_security_selection (market/services.py)
                     -> get_verified_security_search_item (re-verifies via search)
                     -> get_or_create_verified_security (unique symbol+mic_code, select_for_update)
  -> updateSelectedSecurity(id, security)          sets selectedSecurity + selectedSecurityId,
                                                    persists localStorage
  -> market-data effect -> marketDataApi.daily({securityId}) -> GET /api/market-data/daily/?security=<id>
     -> get_security_daily_market_data -> OHLCV -> normalizeMarketData -> buildDashboardPriceChart
```

### State locations

| State | Location |
| --- | --- |
| Selected security | `selectedSecurity` / `selectedSecurityId` in DashboardContent; persisted in `localStorage["aiquantification.dashboard.selectedSecurityId"]` |
| Search query/results/loading/error | `securitySearch` single state slice (createDashboardSearchState) in DashboardContent |
| Search request guard | `securitySearchRequestIdRef` |
| Market-data guard | `marketDataRequestIdRef` + `shouldApplyMarketDataResponse` + `marketDataResponseMatchesRequest` |

### Duplicate search/resolve paths

Only one backend resolver exists: `market/services.py` (`search_security_symbols` +
`resolve_security_selection`), consumed by:

- Dashboard search/resolve: `GET /api/securities/search/`, `POST /api/securities/resolve/`;
- Watchlist add-symbol: `POST /api/watchlist/add-symbol/` (reuses
  `get_verified_security_search_item`);
- Backtest remote security: `BacktestRunSerializer` reuses the same
  `market.services` resolver (tests patch `market.services.search_security_symbols`).

On the frontend there are two search UI components, but they share the same API
and normalization model: `SecuritySearchSelect` (autocomplete combobox; used by
AI Insights / Backtest / legacy Prediction Lab) and `DashboardSecuritySearch`
(explicit Search button; Dashboard only). The Dashboard does **not** call a
legacy endpoint — it calls the same verified remote-resolution API.

---

## 2. Root Causes

### RC-1 (primary, deployed-environment): first-time resolution of a
non-local symbol depends on the live provider

For a symbol that is not already in the deployed database (e.g., AVGO before it
has ever been resolved there), the backend must call Twelve Data
`symbol_search`. When that provider call fails or is rate-limited (free-tier
"API credits exhausted" is a real-world cause), and no local result exists,
the backend returns 429/503. Earlier UI builds collapsed this into a generic
"Unable to search securities" with no diagnosis, which reads as "search does
not work". The backend tests pass for XOM/QQQ because they mock the provider;
the deployed environment has a live provider dependency.

### RC-2 (fixed in round 1/2): selection could be cleared and the UI was
ambiguous

- `updateSelectedSecurity` previously set `selectedSecurity` to `null` when an
  id was not found in the local list (a silent clear path), and the shared
  combobox had edit-clearing semantics.
- The legacy CSS rule `.dashboard-security-search > div:not(.security-search-select)`
  wrapped the new search control in an input-like bordered box, producing the
  "input inside input" double border.
- The UI gave no explicit Search trigger, no visible no-result/error feedback,
  and the placeholder over-promised without examples.

### RC-3 (minor): missing regression coverage for the input matrix and
AVGO/MU cross-symbol stale path

There were no tests pinning case/whitespace normalization, invalid input
feedback, AVGO↔MU stale-response protection, or AVGO/MU remote-resolve
create-once behavior.

---

## 3. Why Previous Fixes Were Insufficient

- **Adding a Search button** fixed the missing trigger and the Enter behavior,
  and **remote regression tests** proved the backend contract with a mocked
  provider. But neither addressed the actual deployment failure mode: a symbol
  absent from the deployed DB whose provider search is unavailable. The UI then
  showed a generic message, so the pilot still perceived "search is broken".
- **Round 2** made the failure explicit (backend detail + provider-degraded
  notice) and fixed the double-border, but did not add evidence for the full
  input matrix (case/whitespace/name/partial/invalid) or the AVGO↔MU stale
  path, and the placeholder still did not communicate what is reliably
  supported.

---

## 4. Symbol Verification Table

Evidence sources: backend probes against the real local database with a fake
provider (no network), the actual frontend model executed with the real backend
payload shape, and the existing/new automated tests.

| Symbol | Search | Select | Market Data | Final |
| --- | --- | --- | --- | --- |
| AVGO | 200, local result (id 10); remote path proven by mock | resolve creates once (new test) | request built with AVGO id; stale MU rejected (new test) | Dashboard shows AVGO |
| MU | 200, local result (id 11); remote path proven by mock | resolve creates once (new test) | same id-based mechanism | Dashboard shows MU |
| XOM | 200, local result (id 20); remote path proven by mock | resolve verified | `test_remote_resolved_xom_serves_xom_ohlcv` (K-line symbol=XOM) | Dashboard shows XOM |
| JPM | 200, local result (id 18); remote path proven by mock | resolve verified (`test_selecting_verified_remote_result_creates_active_security`) | id-based mechanism (regime path also covered) | Dashboard shows JPM |
| QQQ | 200, local result (id 8, ETF) | resolve verified | `test_remote_resolved_qqq_serves_qqq_ohlcv` (K-line symbol=QQQ) | Dashboard shows QQQ |

The chart can never be "top label changed but data still AAPL/SPY": the
market-data request is keyed by the selected security id, and
`marketDataResponseMatchesRequest` rejects any response whose security id,
range or interval differs.

---

## 5. Input Matrix Results (backend probe, local DB + fake provider)

| Category | Query | Result |
| --- | --- | --- |
| Popular / local | SPY QQQ AAPL MSFT NVDA | 1 local result each |
| Valid non-popular | AVGO MU XOM JPM GOOGL AMZN | local results on this DB; remote path proven with mocked provider |
| Case | avgo / AvGo / AVGO | all return AVGO (backend icontains; frontend uppercases symbol) |
| Whitespace | ` AVGO ` / `AVGO ` / `  AVGO  ` | trimmed; identical result |
| Company name | Broadcom→AVGO, Exxon Mobil→XOM, JPMorgan→JPM, Apple→AAPL, Micron→MU | supported via local name `icontains` (provider name search is best-effort) |
| Partial | AVG→AVGO, Broad→AVGO, Micro→MSFT/MU/AMD | supported via local `icontains`; substring matching can return extra rows (e.g. "MU" also matches XLC because "mu" appears in "Communication") |
| Invalid | ABCDEFGINVALID / 123XYZ / !@#$ / X | count=0 → "No matching securities found." (backend min 2 chars) |
| Provider failure, no local match | (deployed DB without symbol) | backend 429/503 → UI: "Unable to search securities. Please try again." + backend detail |
| Provider failure, local match exists | AVGO etc. | backend 200 local + `remote_error` → UI shows results + provider note |

### Backend-direct vs frontend comparison (same endpoint, same payload)

| Symbol | Backend direct (`GET /api/securities/search/`) | Frontend (`mergeSecuritySearchOptions`) | Result |
| --- | --- | --- | --- |
| AVGO | 200, items=[AVGO], id 10, source local | AVGO merged with id 10 | Match |
| MU | 200, items=[MU, XLC], id 11 local | MU merged (remote shape id null in probe) | Match |
| XOM | 200, items=[XOM], id 20 local | XOM merged | Match |
| JPM | 200, items=[JPM], id 18 local | JPM merged | Match |
| QQQ | 200, items=[QQQ], id 8 local | QQQ merged | Match |

Conclusion: for any symbol that exists locally (or whose provider search
succeeds), backend and frontend agree. The pilot failure for symbols absent
from the deployed DB is upstream of this parity — it is the live provider call
and the deployed DB state.

---

## 6. UI Verification

- **Layout**: one plain flex row — input (`flex: 1`, single border/radius) +
  Search button (fixed right, same 42px height, 10px gap). The outer wrapper
  has no input-like border/background (legacy CSS rule removed).
- **Placeholder**: now `Search symbol or company name, e.g. AVGO` (company-name
  search is genuinely supported; the example makes the capability explicit).
- **Loading**: button disabled and shows "Searching...".
- **Results**: clickable list with symbol, name, exchange, Local/Remote badge.
- **No result**: "No matching securities found."
- **Error**: "Unable to search securities. Please try again." plus the backend
  detail (e.g. rate-limit message).
- **Provider degraded with local results**: results shown plus a notice with
  the backend `remote_error`.
- **Selection flow unified**: Popular chips and search results both end in
  `selectSecuritySearchResult` → the same resolve/selection logic.

---

## 7. Tests Run

| Suite | Run | Passed | Failed |
| --- | ---: | ---: | ---: |
| Frontend `npm test` | 225 | 225 | 0 |
| Backend `market` + `backtest.tests.MarketRegimeBacktestApiTests` | 147 | 147 | 0 |
| New backend resolve tests (AVGO/MU/GOOGL create-once) | 3 | 3 | 0 |
| Production build `npm run build` | — | pass | 0 |

### Added tests this round

- `market/tests_market_data.py`: `test_remote_resolve_avgo_creates_active_security_once`,
  `test_remote_resolve_mu_creates_active_security_once`,
  `test_remote_resolve_googl_creates_active_security_once` (remote resolve
  creates an active Security once; a second resolve reuses the same row).
- `frontend/.../dashboardSearchModel.test.js`: case/whitespace normalization of
  AVGO; full sequence test (type → loading → failure never touches selection).
- `frontend/.../dashboardSecurityModel.test.js`: switching to AVGO builds an
  AVGO market-data request and rejects a stale MU response.

Existing guards preserved: `securitySearchRequestIdRef`, `marketDataRequestIdRef`,
`shouldApplyMarketDataResponse`, `marketDataResponseMatchesRequest`, and all
prior stale-response tests (SPY→XOM) remain green.

---

## 8. Remaining Limitations

- **Ticker vs company-name**: ticker search is fully supported. Company-name
  and partial search are reliably supported against the local database
  (`icontains`); against the remote provider they are best-effort and depend on
  Twelve Data `symbol_search`.
- **Provider dependency**: a symbol that is neither local nor resolvable
  because the provider is down/rate-limited cannot be added (by design — no
  auto-insertion on failed search). The UI now states this explicitly. Running
  `seed_securities` and resolving symbols once (when the provider is healthy)
  populates the database so later searches work offline.
- **Caching**: backend search cache (300s) and frontend client cache (5 min)
  can briefly serve an earlier empty result for the same query.
- **Keyboard navigation**: results are mouse/touch-clickable; arrow-key
  navigation of the result list is not implemented.
- **Deployment state**: the deployed database may not contain symbols present
  in this local database; provider availability must be confirmed with backend
  request logs (429/503 vs 200-empty) before drawing final conclusions about
  the deployed pilot.
