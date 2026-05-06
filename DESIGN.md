# Master Paper Trade Lab — Design Document

> A research platform for paper-trading prediction-market strategies (Polymarket primary, Kalshi/Deribit secondary), with rigorous fill simulation, full-matrix analytics, and clean strategy promotion gates.

**Status**: Phase 0 scaffolding
**Owner**: elmorshedydel
**Repo**: `elmorshedydel/master-paper-trade-lab` (private)
**Hosting**: Railway (3 services: Worker+API, Web, Postgres)
**Budget**: ~$35–40/mo

---

## 1. Product framing

This is **a research platform**, not a trading bot. The 20+ strategies are research experiments run on the platform; they are not features of the platform. The platform's job is to:

1. Record everything that's not cleanly downloadable online (Polymarket internals, activity feed, news firehose, Kalshi, Deribit)
2. Run strategies in any of four runtime modes with hot-reloadable config
3. Simulate fills as rigorously as possible without real-money calibration; allow real-money calibration as an opt-in upgrade
4. Replay any strategy against any past time window with any parameter overrides — one click
5. Show a clean, modern dashboard that pivots P&L across many tagged dimensions
6. Enforce promotion gates so no strategy reaches paper-capital deployment without passing replay → log → signal → full

Each strategy thereafter is its own research project with its own `DESIGN.md`, validation tests, and observation journal. Nothing is rushed.

---

## 2. Strategy lifecycle (the rigor model)

Every strategy moves through gates. Each gate has explicit pass criteria.

```
[idea] → DESIGN.md → implementation → synthetic tests
                                             ↓
                                    replay_only (90d backtest)
                                             ↓ pass criteria
                                       live_log (1–2 weeks observation)
                                             ↓ signals match replay
                                     live_signal (1–2 weeks fill observation)
                                             ↓ fills behave per model
                                       live_full ($5k paper sleeve)
                                             ↓ ongoing kill criteria
                                          [graduated to real $] or [killed]
```

Promotion is YAML config change. No code change. No restart.

### Runtime modes

| Mode | Capital | Signals | Fills | P&L tracked |
|---|---|---|---|---|
| `replay_only` | — | — | — | only in Strategy Lab replays |
| `live_log` | none | yes (logged) | — | — |
| `live_signal` | none | yes | simulated | fill stats only |
| `live_full` | $5k default | yes | simulated | full sleeve |

---

## 3. Realism model — the haircut

Default platform haircut applied to headline P&L: **−22%**

| Friction source | Haircut | Empirical anchor |
|---|---|---|
| Slippage beyond fill-sim model | −7% | Aldridge (2013); Brogaard/Hendershott/Riordan (2014) |
| Maker fill probability shortfall | −6% | Hendershott (2013): live maker fill ~70% vs paper ~100% |
| Latency tail | −4% | Tail latency >3s during congestion |
| API rejection / network failure | −2% | Polymarket community-reported 2–3% rejection rate |
| Residual adverse selection | −3% | Beyond fill-sim; tightened by Tier 3 calibration |
| **Total** | **−22%** | |

Strategy classes can override:

| Class | Override | Reason |
|---|---|---|
| Pure arb | −18% | Math edge; frictions are gas + minor slippage |
| Maker/passive | −38% | Queue + adverse selection dominate |
| Latency-sensitive | −28% | Latency tail bites harder |
| Slow (EOD whale copy) | −15% | Plenty of time, low friction |

After Tier 3 calibration (~3 months in), all become empirical per-strategy.

References:
- Aldridge — *High-Frequency Trading: A Practical Guide* (2013)
- Brogaard, Hendershott, Riordan — *High-Frequency Trading and Price Discovery*, RFS (2014)
- Hendershott et al. — *Does Algorithmic Trading Improve Liquidity?*, JFE (2013)
- Shleifer & Vishny — *The Limits of Arbitrage*, JF (1997)

---

## 4. Fill simulation (Tier 2)

Default fidelity: event-tape replay with queue tracking. Tier 3 calibration hooks present, off by default.

### Algorithm

1. **Pre-flight realism filter**
   - Order size > 10% of resting depth at price → "would-have-moved-market" flag, +50% slippage haircut
   - Spread > 3¢ → "thin market" flag, queue-decay penalty applied

2. **Latency injection** (system constant, not a config dim — see §5)
   - Default end-to-end: **1500 ms** (250 decision + 250 code + 1000 network buffer)
   - Configurable per fill simulator instance, not per strategy

3. **Taker fills**
   - Walk orderbook ladder until size satisfied
   - Weighted-average fill price across consumed levels
   - Apply gas haircut ($0.10 fixed)

4. **Maker fills (queue model)**
   - On placement: snapshot `Q_ahead` = resting size at-or-better than our price
   - For each subsequent CLOB event at-or-through our price:
     - Trade event → decrement `Q_ahead` by trade size; if `≤0`, fill us at our price
     - Cancel event (depth decrease, no trade) → decrement `Q_ahead × cancel_decay_factor` (default 0.5)
     - Add event → ignored (new orders queue behind us)
     - Price-walk-away (book moves past with no trade at our price) → mark as missed, no fill
   - Post-fill: track 60s adverse move; tag as "picked off" if price moves ≥2¢ against us

5. **Validation pass**
   - Every paper fill is "tentative" for 5 min
   - Re-check tape; if fill price was outside actual trading range → flag `realism_flag = implausible`, exclude from headline P&L

6. **Conservative bias**
   - Ambiguity defaults to "no fill"
   - Worst-case queue position assumed
   - Realism haircut applied to displayed P&L

### Tier 3 calibration (off by default)

- Optional: small wallet ($50–200) with EOA private key
- 1–2% of paper orders shadowed by real $1–5 orders
- Records `paper_predicted_fill` vs `actual_fill` per market
- Updates per-market fill-probability and slippage corrections
- Feature toggle: `system.calibration_mode = on`

---

## 5. The configuration matrix

### NOT in the matrix (system constants or computed-later)

| Cut | Reason |
|---|---|
| Latency | Infrastructure property; fixed at 1500ms for production. One-off "speed sensitivity" replay button on the dashboard. |
| Allocation across sleeves | Computed post-hoc from trade log via `Allocator` plugin family in month 3+. V1 = equal $5k flat. |

### IN the matrix (genuinely unknown without data)

| Dim | Variants |
|---|---|
| Strategy | the 20+ strategy files |
| Size profile | small / medium / large |
| Threshold profile | tight / loose |
| Holding profile | quick-flip / hold-to-resolution / hybrid |
| Market filter | all-eligible / category-restricted |
| Loss management | none / -30% stop / -50% stop |
| Concurrent position cap | tight / wide |

Each strategy's author defines 3–5 named config bundles, not the cartesian. ~3 configs × 20 strategies = ~60 sleeves at full deployment.

---

## 6. Analytics matrix — trade tags

Every paper trade is tagged on fill with these dimensions. All are pivotable in the dashboard.

| Tag | Examples |
|---|---|
| `strategy_id` | `cross_outcome_arb`, `weather_tail_sell` |
| `config_id` | `default`, `aggressive`, `conservative` |
| `mode` | `live_full`, `live_signal`, `live_log` |
| `market_category` | politics, weather, sports, crypto-event, esports, finance, pop-culture |
| `market_subcategory` | `weather/nyc/temp`, `nfl/regular-season`, `election/2026` |
| `market_liquidity_bucket` | thin / medium / thick (24h volume) |
| `entry_price_bucket` | <$0.05, $0.05–0.25, $0.25–0.75, $0.75–0.95, >$0.95 |
| `time_to_resolution_bucket` | <1h, 1–24h, 1–7d, >7d |
| `orderbook_state_bucket` | thin / medium / thick at TOB |
| `fill_type` | taker, maker-fast (<10s), maker-slow (>10s), missed |
| `realism_flag` | clean, would-have-moved-market, implausible |
| `time_of_day_utc_bucket` | 0–6, 6–12, 12–18, 18–24 |
| `day_of_week` | 0–6 |
| `news_regime` | calm, news-event, post-event |
| `counterparty_estimate` | unknown, retail, sharp |
| `tags_extra` (JSONB) | open extension |

---

## 7. Data ingestion — what we record

| Pipe | Source | Cost | Strategies it feeds |
|---|---|---|---|
| Polymarket CLOB websocket | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | free | almost all |
| Polymarket activity feed | Polymarket public data API | free | whale copy/fade, sharp follow-up |
| News firehose (RSS) | Reuters, AP, BBC, CNN, Bloomberg headlines, ESPN | free | news-driven directional |
| Reddit feed | Reddit API (public) | free | reddit_sentiment_lead |
| Kalshi data | Kalshi public market API + WS | free | cross_venue_arb_kalshi |
| Deribit options | `wss://www.deribit.com/ws/api/v2/` | free | crypto IV arb |
| Binance/OKX perp ticker | public WS | free | crypto basis |

**External data NOT recorded** (downloadable historical when needed for backtest):
- Crypto spot OHLCV (Binance historical)
- Weather actuals (NOAA, Visual Crossing)
- Sports outcomes (any stats API)
- Equity / FX / rates

### Storage retention

- Raw events: 7 days
- 1-min bars: 30 days
- Daily bars: forever
- Steady-state DB: ~5–8 GB

---

## 8. Strategy roster (V1)

### Tier A — `live_full` execution-test (6 strategies, $5k each)

These need live capital because execution dynamics ARE the test:
1. `cross_outcome_arb`
2. `basket_arb`
3. `redemption_sniper`
4. `weather_tail_sell`
5. `weather_tail_buy`
6. `maker_passive`

### Tier B — `live_full` edge-watch (14 strategies, $5k each)

Real-time data, plausible edge, deploy paper capital and watch in real time:
- `whale_copy_eod`, `whale_fade_inplay`
- `stale_price_crypto`
- `cross_market_correlation`, `multi_outcome_drift`
- `mean_revert_post_spike`, `momentum_orderbook`
- `weather_resolution_arb`
- `news_to_market_lag`, `news_directional_politics`, `news_directional_crypto`
- `cross_venue_arb_kalshi`
- `polymarket_vs_deribit_iv_btc`, `polymarket_vs_deribit_iv_eth`

### Tier C — `live_signal` / `live_log` (5 strategies, no capital)

Logged or fill-stats-only until proven worth a sleeve:
- `news_directional_sports` (live_log)
- `reddit_sentiment_lead` (live_log)
- `polymarket_vs_perp_basis` (live_signal)
- `late_resolver_arb` (live_signal)
- `stale_price_sports` (live_log)

### Tier D — `replay_only` (3 strategies)

Need historical bootstrap before they can produce meaningful signals:
- `sharp_wallet_followup` (60+ days of activity feed needed)
- `redemption_pattern_retail` (N resolutions needed)
- `sports_resolution_arb` (sports outcomes DB needed)

### Truly omitted

- Cross-venue arb requiring venue we don't access (e.g., Limitless without API)
- Mempool / front-running on-chain (archive node infra)
- Insider-info plays

---

## 9. Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Worker+API (Python, single async process on Railway)    │
│  - Ingestion pipes (per-pipe enabled flag)              │
│  - In-memory orderbook reconstruction                   │
│  - Strategy runners (mode-aware)                        │
│  - Fill simulator (Tier 2; Tier 3 hooks present)        │
│  - Position/PnL tracker                                 │
│  - Tag system (auto-applied to every fill)              │
│  - FastAPI endpoints for the web UI                     │
│  - Replay engine                                        │
│  - Periodic jobs (retention, redemption sweep, daily P&L roll) │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
                   ┌──────────────┐
                   │  Postgres    │
                   │  (Railway)   │
                   └──────┬───────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│ Web (Next.js 14, shadcn/ui + Tremor, dark by default)   │
│  - Overview                                             │
│  - Sleeve detail                                        │
│  - Matrix / Pivot Explorer                              │
│  - Trade Explorer                                       │
│  - Failure Analysis                                     │
│  - Strategy Lab (replay)                                │
│  - System Health (sidebar)                              │
└─────────────────────────────────────────────────────────┘
```

---

## 10. Plugin auto-discovery

The runner scans these directories on startup and on file change:

- `src/strategies/<name>/strategy.py` → must implement `Strategy` protocol
- `src/venues/<name>.py` → must implement `MarketDataSource`
- `src/execution/<name>.py` → must implement `FillSimulator`
- `src/analytics/tags/<name>.py` → must implement `Tag`
- `src/analytics/metrics/<name>.py` → must implement `Metric`

No central registry. Drop file → it's discovered → it's available.

---

## 11. Configuration

Per-sleeve YAML at `src/configs/sleeves/<sleeve_id>.yaml`. Hot-reloaded on file change. Every change is a git commit; every trade is tagged with the config-version hash.

Per-system YAML at `src/configs/system/`:
- `runtime.yaml` — global mode toggles, latency model, haircut overrides
- `pipes.yaml` — ingestion pipes on/off
- `markets.yaml` — which markets to subscribe to (top N by volume + always-on lists)

---

## 12. Dashboard pages — purpose-driven

| Page | Single-sentence test |
|---|---|
| Overview | "I look at this for 10 seconds and know the state of everything." |
| Sleeve Detail | "I click a sleeve, see equity curve + every trade with reason." |
| Matrix / Pivot | "Pick any 2 dimensions, get a heatmap of P&L." |
| Trade Explorer | "Filter to a specific scenario, inspect every trade." |
| Failure Analysis | "Show me losses bucketed by failure mode." |
| Strategy Lab | "Click 'Replay strategy on last 60 days,' get full report." |
| System Health (sidebar) | Ingestion lag, DB size, error counts. |

Design rule: every page answers ONE question.

---

## 13. Phasing

| Phase | Duration | Deliverable |
|---|---|---|
| 0 | 3–4 days | Repo, services provisioned, schema, core interfaces, plugin loader, config system |
| 1 | 1 week | All 6 ingestion pipes + retention/aggregation + System Health sidebar |
| 2 | 1 week | Tier 2 fill simulator + position tracker + sleeve P&L + synthetic tests; Tier 3 hooks present |
| 3 | 1 week | All 6 dashboard pages + replay engine + Strategy Lab + tag system |
| 4 | 1 week | Strategy template + 1 reference strategy (`cross_outcome_arb`) end-to-end |
| 5+ | ongoing | Strategies one-by-one with full rigor, ~1–2/week |

Total platform effort: ~4 weeks. Strategies thereafter on individual cycles.

---

## 14. Open decisions (deferred)

- News API upgrade ($29/mo Polygon News) — defer until news strategies prove worth it
- Sports Odds API ($30/mo) — defer; sports outcomes are downloadable historical
- Kalshi trading account / cross-venue real money — out of V1 scope
- Real-money calibration wallet — opt-in feature, off until user funds it

---

# 15. CHANGELOG — what evolved after the original plan

The sections above (1–14) are the **original plan as written before any
implementation**. Every change since is appended here so we always have
both: what the plan was, and what we learned that changed it. Anything in
this section overrides the original where they disagree; nothing is
deleted from §1–14.

## 15.1 — Honest slippage replaces the literature-based haircut

> **Inspired by:** `agent-next/polymarket-paper-trader`'s stance —
> *"paper P&L matches real P&L within the spread."* Their argument: walking
> the actual orderbook level-by-level produces measurable slippage; you
> don't need a generic haircut on top of that.

**Original plan (§3):** apply a flat **−22% realism haircut** to all
displayed P&L, justified by Aldridge (2013) / Brogaard et al. (2014) /
Hendershott et al. (2013) — HFT-equity literature on paper-to-live
degradation. Per-edge-class overrides (`pure_arb` −18%, `maker` −38%,
`tail` −25%, etc.) layered on top. The haircut was the headline number
on the dashboard.

**What we learned:**
- The cited literature is for **HFT in equities**, not Polymarket binary
  prediction markets. Different microstructure (continuous vs binary
  outcomes, different spreads, different counterparty mix). Borrowing a
  flat constant from one to estimate the other is unprincipled.
- We were already walking the book level-by-level in `_fill_taker`. The
  slippage was being **computed and discarded**.
- The single largest, measurable, unambiguous gap from paper to real money
  on Polymarket is **the spread you cross when you take liquidity**. We
  can measure it per trade.

**What changed:**
- `Fill.slippage_bps` and `Trade.slippage_bps` added as first-class data
  fields, computed in `_fill_taker` from the walk it already did.
- Sign convention: positive bps always means "cost to us" (paid above mid
  on a buy, sold below mid on a sell), so it sorts intuitively.
- Schema: `paper_fills.slippage_bps` and `paper_trades.slippage_bps`
  columns added with idempotent `ALTER TABLE ADD COLUMN IF NOT EXISTS`,
  so existing DBs migrate cleanly without data loss.
- New metric plugin `avg_slippage_bps` (lower-is-better) appears on every
  sleeve scorecard.
- New pivot dimension `slippage_bucket` on the matrix page
  (0-10bps / 10-25 / 25-50 / 50-100 / 100+). The matrix can now slice P&L
  by measured friction.
- The realism haircut is **kept in the data model** (`pnl_after_haircut_usd`)
  and the per-edge-class overrides remain in `runtime.yaml` for
  backwards-compat with already-recorded trades — but it's **demoted from
  the headline**. The new headline metric for "what this strategy actually
  costs to run" is `avg_slippage_bps + gas + picked_off_rate`.

**What this means in practice:**
- A pure-arb strategy with 5 bps avg slippage has a 5 bps gap to real
  money, not 18%.
- A maker strategy whose fills overwhelmingly carry `picked_off=True` has
  the picked-off rate as its honest gap, not 38%.
- A directional strategy with 80 bps avg slippage tells you the strategy's
  edge has to clear 80 bps + gas + execution latency — all measurable.

## 15.2 — Stale-book REST fallback (live_full only)

> **Inspired by:** `agent-next/polymarket-paper-trader`'s "no caching,
> always live from API" rule. They eliminate WS-vs-reality drift entirely
> by never trusting a cached book.

**Original plan:** the in-memory `OrderBookStore` (populated by the
Polymarket WS feed) is the canonical source for fill-time book lookups.

**What we learned:** during reconnect / backoff / network blips, the WS
can fall behind the actual book by seconds to minutes. Walking a stale
book defeats the slippage-honesty stance — we'd be paying yesterday's
prices.

**What changed:**
- `Runner._refresh_stale_book_if_needed` checks `book.last_update_ts`
  against `STALE_BOOK_THRESHOLD_SECS = 2.0` before submitting any
  `live_full` order.
- If older than the threshold, calls `PolymarketCLOB.fetch_book_rest`
  which hits the REST `/book?token_id=...` endpoint and replaces the
  snapshot in STORE.
- Replay mode is **unaffected** — replay must use the recorded book at
  the simulated event time; that's the right behavior there.
- Best-effort: if the REST call fails, we proceed with the stale book
  rather than refusing the order. The realism flag system still tags
  the trade. The trade-off: occasional stale fills are honest about their
  staleness; refusing the order would hide trade activity entirely.

## 15.3 — Original 22% haircut: kept in data, hidden in UI

To preserve the historical record, this CHANGELOG and the original §3
are both authoritative for the data they describe:

- **Pre-existing trades** in the DB carry `pnl_after_haircut_usd`
  computed with the literature-based haircut. The API still returns it
  for those rows.
- **New trades** carry both `pnl_after_haircut_usd` (legacy) AND
  `slippage_bps` (new headline). The dashboard UI shows the slippage
  tile on the sleeve scorecard and the slippage_bucket dimension on the
  matrix.
- The **literature haircut justification in §3 is preserved** above
  because that's what was true when those rows were written. It is no
  longer the recommended interpretation of headline P&L going forward.
