# basket_arb — Strategy Design Document

> Status: implemented · replay_only
> Edge class: `pure_arb`

---

## 1. Thesis
A multi-outcome Polymarket market (N ≥ 3 outcomes) must redeem to exactly $1.00 collectively — the winning outcome pays $1, all others $0. When the sum of best asks across all known outcomes is less than $1.00, buying one of each token locks in a guaranteed profit at resolution.

## 2. Mechanics
For every market the strategy has observed, maintain a per-asset book derived from CLOB events. On each book update:

```
sum_asks = Σ best_ask(asset_i) over observed assets in market
gross_edge_bps = (1.00 - sum_asks) * 10_000
```

Fire **N** signals — one BUY per outcome at LIMIT just-above-ask — when:
- We have observed ≥ `min_legs` legs for the market
- `sum_asks <= max_sum_threshold`
- `gross_edge_bps >= min_edge_bps`
- No active arb already on this market

Hold to resolution. The winning leg redeems to $1; losing legs to $0. Combined payout = $1 across the basket regardless of which outcome wins.

## 3. Data dependencies
| Source | What | Required |
|---|---|---|
| Polymarket CLOB | book snapshots + deltas | yes |
| Polymarket markets meta | asset_id count per market (via MARKET_META) | recommended (validates `min_legs`) |

## 4. Entry rules
```
WHEN observed_legs >= min_legs (default 3)
  AND sum_asks <= max_sum_threshold (default 0.98)
  AND gross_edge_bps >= min_edge_bps (default 200)
  AND no open arb for this market
  AND active_arbs < max_concurrent_positions
EMIT N×Signal(BUY, asset_i, LIMIT @ ask_i + price_buffer, size = max_size_per_leg / ask_i)
```

## 5. Exit rules
Hold to resolution. No active exits, no rebalancing. (Same as cross_outcome_arb.)

## 6. Sizing logic
Per-leg notional capped at `max_size_per_leg_usd`. Tokens = `notional / best_ask`. Total deployed per arb = N × per-leg cap.

## 7. Risk rules
- `max_concurrent_positions` (default 10 — fewer than cross_outcome because each arb deploys more capital)
- `max_size_per_leg_usd` (default $100)
- A market with discovered legs growing over time is dangerous — if we fire on 3 of 5 legs the strategy can't see, we may have miscomputed the sum. The `min_legs` floor + `max_sum_threshold` margin together provide cover.

## 8. Failure modes
| Mode | Detection |
|---|---|
| Missing leg (we fire on 3 of 5; sum was misleadingly low) | Resolution outcome NOT in our basket → all our legs lose. Detect via post-resolution PnL distribution; thresholds drift below 0 |
| Broken arb (one leg fails to fill) | One signal fills, others don't — same as cross_outcome_arb. Frequency higher with N legs. |
| Slippage cumulative over N legs | N×leg slippage erodes edge faster than 2-leg arb. Tighter `max_sum_threshold` helps. |

## 9. References
- Same `Limits of Arbitrage` framework as cross_outcome_arb. Multi-outcome literature on prediction markets is sparser; the math is identical.

## 10. Validation plan
- Synthetic: 3-leg arb fires when sum < threshold; 2-leg fires only if min_legs allows; sum exactly at threshold respects edge floor; missing leg case handled.
- Replay: ≥ 5 signals on aggressive config in 30-day window; no catastrophic loss > 2× per-leg notional.

## 11. Promotion criteria
Same defaults as platform; use the conservative variant for first live test (max_size $50/leg).

## 12. Kill criteria
- 30-day rolling realized PnL < −20% of capital (worse tolerance than cross_outcome because per-arb size is larger and missing-leg risk is real)
- Implausible flag rate > 10%
