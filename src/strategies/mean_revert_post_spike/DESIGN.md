# mean_revert_post_spike — Strategy Design Document

> Status: implemented · replay_only
> Edge class: `directional` (haircut −22%)

---

## 1. Thesis
Polymarket binary markets sometimes spike sharply on retail-flow shocks (e.g., a single big bet, a thin-book sweep) and partially revert when the news that "caused" the spike turns out to be misread. Without a fill-driven exit mechanism, the strategy expresses this as a **resolution-direction bet** taken right after a detected spike: the market's spike is more likely an overreaction than a fundamental repricing, so the eventual resolution is biased toward the pre-spike consensus.

## 2. Mechanics
For each asset we observe:
- Maintain a rolling price window (last `window_secs`)
- On each book event, compute `pct_change = (current_mid - oldest_mid_in_window) / oldest_mid_in_window`
- If `|pct_change| >= spike_threshold_pct` AND current price is in `[min_tradeable_price, max_tradeable_price]`:
  - Fire BUY signal in **OPPOSITE** direction of the spike (fade)
  - For an upward spike: BUY at the asset that just dropped (the paired side); but at platform level we don't know paired side, so we BUY on the SAME asset_id at the new price, which means betting the price comes back down. Because Polymarket is binary, `BUY` at high price is a "the resolution will be NO" bet — exactly the fade direction we want.

V1 simplification: the strategy doesn't care about pair identity. It just notes "this asset spiked up to 0.75; we expect it back to 0.55, so resolution is more likely NO than YES; BUY the lower-priced side which means SELLING this side". Without sell capability we BUY the asset that's currently CHEAP. Concretely:
- Upward spike on asset X (X went from 0.55 → 0.75): wait. Buying X at 0.75 is buying the asset that spiked — we'd be momentum-following. That's wrong.
- The fade is to BUY the OTHER outcome's asset (which dropped from 0.45 → 0.25) at the now-low price.

So the strategy needs to know the paired asset. Use `_market_assets` (same pattern as cross_outcome_arb) — when we have 2+ assets observed in a market and one spikes up, we BUY a different asset in the same market.

## 3. Data dependencies
- Polymarket CLOB: book events
- Polymarket markets meta: not strictly required (binary heuristic); paired asset comes from observed event stream

## 4. Entry rules
```
WHEN any observed asset_id in market has rolling_pct_change >= spike_threshold_pct
  AND we know at least 2 assets in this market
  AND the OTHER asset's current best_ask is in [min_price, max_price]
  AND no recent fade fired on this market within fade_cooldown_secs
EMIT BUY on the *other* asset (the dropped one) at LIMIT just-above-ask
```

## 5. Exit rules
Hold to resolution. The strategy is implicitly a directional bet on resolution; not a TP-driven mean-revert.

## 6. Sizing logic
Modest — `target_notional_usd` default $50. The strategy is high-variance and we don't want concentration.

## 7. Risk rules
- `max_concurrent_positions` (default 30)
- Per-market cap = `target_notional_usd`
- Skips if current price is outside tradeable band — too cheap/expensive means edge has likely already moved

## 8. Failure modes
| Mode | Detection |
|---|---|
| Spike was actually right (real news, real repricing) | resolution goes against us; we lose ~price-paid |
| Multiple markets correlated, all spike together (same news) | clustered losses; visible in matrix by news_regime tag |
| Pair detection wrong — we BUY the same asset that spiked | implementation bug; covered by tests |

## 9. References
- Mean-reversion in equity markets has decades of literature; transferring to event markets is heuristic.

## 10. Validation plan
- Synthetic: spike detection across rolling window; fade direction; cooldown.
- Replay: ≥ 5 signals in 30-day window on aggressive config.

## 11. Promotion criteria
Default platform thresholds, plus require positive replay PnL at gate to live_log.

## 12. Kill criteria
- 30-day rolling PnL < −20% of capital
- Win rate < 35% over last 200 trades (the 50/50 floor + a little margin)
