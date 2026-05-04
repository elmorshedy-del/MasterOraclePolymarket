# momentum_orderbook — Strategy Design Document

> Status: implemented · replay_only
> Edge class: `latency_sensitive` (haircut −28%)

---

## 1. Thesis
Heavy depth on one side of an asset's order book signals near-term direction — large resting bids relative to asks indicate buying pressure that hasn't yet been absorbed. Trading in the direction of imbalance (BUY when bid-heavy, BUY paired when ask-heavy) captures the move before the imbalance dissipates.

## 2. Mechanics
For each book event with an updated TOB:
- Compute imbalance = `bid_size_at_top / (bid_size_at_top + ask_size_at_top)`
- If imbalance >= `bullish_threshold` (default 0.75): BUY the asset at LIMIT just-above-ask
- If imbalance <= `bearish_threshold` (default 0.25): BUY the **paired** asset (we don't short)
- Tradeable band: only fire when current price is in `[min_price, max_price]` (default 0.20–0.80)
- Per-(market, asset) cooldown to prevent spam

V1 holds to resolution. The platform doesn't yet have TP-driven exits, so the strategy is implicitly a directional bet on the resolution outcome rather than a short-term momentum chase.

## 3. Data dependencies
- Polymarket CLOB only (book + delta events)

## 4. Entry rules
```
WHEN best_bid AND best_ask both exist
  AND bid_size + ask_size >= min_tob_depth_usd / mid (i.e. tob has real money)
  AND imbalance >= bullish_threshold  → BUY this asset at ask
  OR  imbalance <= bearish_threshold  → BUY *paired* asset at its ask
  AND current price in [min_price, max_price]
  AND no recent fire on this (market, asset) within cooldown_secs
EMIT
```

## 5. Exit rules
Hold to resolution.

## 6. Sizing logic
`target_notional_usd / price`. Default $40 — small per-trade because the strategy fires often and we want diversification.

## 7. Risk rules
- `max_concurrent_positions` (default 60)
- Per-market cap = 2 × `target_notional_usd` (one signal can fire on each direction across two assets per market)
- Skip thin TOB (`min_tob_depth_usd` default $200)

## 8. Failure modes
| Mode | Detection |
|---|---|
| Imbalance was a stale signal — book moves before we fill | implausible flag rate spikes; fill_type missed grows |
| Imbalance was deliberate manipulation | replay shows clustered losses; matrix counterparty_estimate tag flags |
| Bullish + bearish fires alternate on same market within seconds | cooldown should prevent; if it doesn't, a bug |

## 9. References
- Aldridge (2013) on book-imbalance signals; survives in equity HFT but degrades fast at retail latencies. We expect the haircut −28% (latency_sensitive class) to capture the gap.

## 10. Validation plan
- Synthetic: imbalance threshold; pair lookup; cooldown; depth filter.
- Replay: ≥ 30 signals on aggressive config in 30-day window.

## 11. Promotion criteria
- `latency_ms` override test in Strategy Lab: re-run at 100ms vs 1500ms and compare PnL. Promotion to live_log requires the 100ms PnL > 1500ms by ≥ 50% (i.e., the strategy is genuinely latency-sensitive).

## 12. Kill criteria
- 30-day rolling PnL < −20% of capital
- 100ms replay PnL < production PnL (means our latency model isn't the bottleneck — strategy edge isn't real)
