# maker_passive — Strategy Design Document

> Status: implemented · replay_only
> Edge class: `maker` (haircut −38% — queue + adverse selection dominate)

---

## 1. Thesis
On thick liquid markets, placing limit orders 1¢ inside the best bid and best ask captures the bid-ask spread when both fill. Real-world maker fill rate is well below 100% and adverse-selection bites, but the math is positive on enough markets that a properly throttled passive strategy yields a small consistent edge.

## 2. Mechanics
For each top-volume market we observe (`min_24h_volume_usd` filter):
- Once per `place_interval_secs` per (market, asset, side) — emit a LIMIT at:
  - `best_bid + tick_size` (passive bid)
  - `best_ask - tick_size` (passive ask)
- Sized by `target_notional_usd`.
- Don't track our own orders; rely on the platform's fill simulator to handle fill / walk-away / cancel-on-TTL behavior.

This V1 doesn't actively cancel-and-replace; the fill sim's MISSED detection plus a fresh placement every `place_interval_secs` approximates that.

## 3. Data dependencies
| Source | What | Required |
|---|---|---|
| Polymarket CLOB | book + tick-size | yes |
| Polymarket markets meta | 24h volume, tick_size | yes |

## 4. Entry rules
```
WHEN market 24h volume >= min_24h_volume_usd (default $5000)
  AND best_bid + best_ask both exist with spread >= 2 * tick_size
  AND time since our last placement on this (market, asset, side) >= place_interval_secs
EMIT
  Signal(BUY,  asset_id, LIMIT @ best_bid + tick_size, size = target_notional_usd / mid)
  Signal(SELL, asset_id, LIMIT @ best_ask - tick_size, size = target_notional_usd / mid)
```

## 5. Exit rules
The fill simulator handles MISSED (book walked away) automatically. There are no explicit exits; resting orders either fill or expire.

## 6. Sizing logic
`target_notional_usd / mid_price`. Default $50/order. Two-sided: $100 deployed per market per cycle.

## 7. Risk rules
- `max_concurrent_positions` (default 50)
- Per-market cap = `2 * target_notional_usd`
- Skip illiquid markets (volume filter)
- Skip markets with crossed/locked books

## 8. Failure modes
| Mode | Detection |
|---|---|
| Adverse selection | `realism_flag = picked_off` rate climbs in sleeve detail page |
| Maker fills don't happen at predicted rate | `fill_rate` metric below replay-predicted |
| Spread too narrow to capture | observed: many emissions, few fills, low PnL |
| Exit-side fill rate << entry-side (we accumulate one direction) | sleeve open positions show net imbalance |

## 9. References
- Aldridge (2013) chapter on market-making strategies
- Hendershott et al. (2013) on maker-fill rates in retail-order presence

## 10. Validation plan
- Synthetic: fires when volume + spread filters pass; respects place_interval cooldown; skips illiquid.
- Replay: signals fire on top markets; fill rate measured directly via paper_fills.

## 11. Promotion criteria
- replay_only → live_log: ≥ 200 signals, fill rate (filled / placed) > 5%
- Tighter implausible threshold than default: ≤ 3% (maker quality is the test)

## 12. Kill criteria
- 30-day rolling PnL < 0 (this strategy is supposed to make small consistent money — losses mean it's broken)
- picked-off rate > 50% (adverse selection has won)
