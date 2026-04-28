# Phase plan

Platform first; strategies sequenced individually after.

## Phase 0 — Scaffolding (3–4 days) — **CURRENT**

Goal: an empty platform that boots, with all interfaces and contracts in place.

- [x] Repo structure
- [x] `DESIGN.md` (canonical spec)
- [x] Core interfaces (`Strategy`, `MarketDataSource`, `FillSimulator`, `Tag`, `Metric`, `Allocator`)
- [x] Event/data models (`Side`, `OrderType`, `MarketEvent`, `OrderBook`, `Signal`, `Order`, `Fill`, `Trade`, etc.)
- [x] Plugin auto-discovery loader
- [x] YAML config system with hot reload (`runtime.yaml`, `pipes.yaml`, `markets.yaml`, per-sleeve YAML)
- [x] Postgres schema
- [x] Strategy template + onboarding workflow
- [x] FastAPI surface (health/version)
- [x] Next.js dashboard skeleton (dark, calm, not Bloomberg)
- [x] Railway/Docker config
- [x] Smoke tests

## Phase 1 — Ingestion (1 week)

Goal: data is flowing and recorded; system health is visible.

- Polymarket CLOB websocket adapter (orderbook reconstruction from events)
- Polymarket activity feed adapter
- News RSS adapter (Reuters, AP, BBC, CNN, Bloomberg headlines, ESPN)
- Reddit adapter (off by default until creds configured)
- Kalshi adapter
- Deribit options WS adapter
- Binance/OKX perp ticker adapter
- Event persistence (partitioned `market_events` writes)
- 1-minute bar aggregator + retention sweeper
- System Health sidebar in the dashboard

Acceptance: 24h continuous run, all enabled pipes connected, retention working,
DB growth tracked and within budget.

## Phase 2 — Execution + Position infra (1 week)

Goal: paper fills work correctly, validated against synthetic strategies.

- Tier 2 fill simulator (taker + maker with queue tracking + adverse selection)
- Tier 3 calibration hooks (off by default; wallet/wiring present)
- Position tracker, sleeve P&L
- Validation pass (5-min tentative window, `realism_flag` tagging)
- Synthetic strategy harness for end-to-end fill engine tests

Acceptance: synthetic strategies generating fills correctly across thin/thick
books, taker/maker, with realistic flags applied.

## Phase 3 — Analytics + Replay (1 week)

Goal: dashboard works, can replay any strategy against any time window.

- Tag system (all 14 dimensions of the matrix)
- Metric plugins (Sharpe, max drawdown, win rate, profit factor, capacity)
- Six dashboard pages (Overview, Sleeve Detail, Matrix, Trade Explorer, Failure
  Analysis, Strategy Lab)
- Replay engine with one-click presets and custom builder
- Replay job queue + comparison view (production vs replayed)

Acceptance: open the dashboard, see live equity curves; click "Replay" → get
results within minutes; pivot table works on any 2 dimensions.

## Phase 4 — Strategy onboarding template (1 week)

Goal: a complete platform + 1 reference strategy demonstrating the workflow.

- `strategies/<name>/` folder structure documented and enforced
- Promotion gate machinery (auto-checks promotion criteria)
- `strategies/cross_outcome_arb/` implemented end-to-end with full rigor:
  - DESIGN.md (12 sections, all filled)
  - synthetic tests
  - 30-day replay validation
  - first-run promotion log

Acceptance: cross_outcome_arb passes replay, runs in `live_full` paper mode,
shows up in matrix with all tags applied.

## Phase 5+ — Strategies, one at a time, no rush

~1–2 strategies per week. Each strategy is its own focused cycle:

1. Author writes `DESIGN.md`. Review.
2. Implement `strategy.py` + tests.
3. Replay validate.
4. Promote through `live_log` → `live_signal` → `live_full` per gates.
5. Update `notes/` journal weekly.

Order (by edge confidence, simplest first):

- Tier A live_full (6): cross_outcome_arb (Phase 4), basket_arb,
  redemption_sniper, weather_tail_sell, weather_tail_buy, maker_passive
- Tier B live_full (14): whale_copy_eod, whale_fade_inplay, stale_price_crypto,
  cross_market_correlation, multi_outcome_drift, mean_revert_post_spike,
  momentum_orderbook, weather_resolution_arb, news_to_market_lag,
  news_directional_politics, news_directional_crypto, cross_venue_arb_kalshi,
  polymarket_vs_deribit_iv_btc, polymarket_vs_deribit_iv_eth
- Tier C live_signal/log (5): news_directional_sports, reddit_sentiment_lead,
  polymarket_vs_perp_basis, late_resolver_arb, stale_price_sports
- Tier D replay_only (3): sharp_wallet_followup, redemption_pattern_retail,
  sports_resolution_arb
