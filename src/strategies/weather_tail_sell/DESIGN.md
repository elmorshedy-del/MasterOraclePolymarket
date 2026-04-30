# weather_tail_sell — Strategy Design Document

> Status: implemented (heuristic V1) · replay_only
> Edge class: `tail`

---

## 1. Thesis
Retail systematically overpays for tail-bucket weather outcomes ("temperature exactly 95-97°F") relative to their true probability. Buying NO at $0.95+ on these tails captures the residual when the tail doesn't hit, with payout ~5¢ on every trade and a small adverse-resolution rate.

## 2. Mechanics (V1 heuristic)
For weather-category markets:
- If `best_ask` on any leg is in `[min_price, max_price]` (default $0.95–$0.99)
- AND the leg has not been recently adverse (no print at-or-below `recent_adverse_threshold`)
- Buy NO at LIMIT just-above-ask, sized by `target_notional_usd`.

V1 does NOT have forecast data. The price-only heuristic still works for the "obvious tail" case (very far out buckets) but will under-perform vs the forecast-aware version. Forecast integration is a Phase 6+ enhancement.

## 3. Data dependencies
| Source | What | Required | V2+ |
|---|---|---|---|
| Polymarket CLOB | book + trade prints | yes | yes |
| Polymarket markets meta | category | yes | yes |
| Weather forecast | NOAA / Visual Crossing actuals | no (V1) | yes (V2) |

## 4. Entry rules
```
WHEN market_category in ('weather', ) — case-insensitive substring match
  AND min_price <= best_ask <= max_price
  AND no adverse trade print in last recent_window_secs
EMIT Signal(BUY, asset_id, LIMIT @ ask + buffer, size = target_notional / ask)
```

## 5. Exit rules
Hold to resolution.

## 6. Sizing logic
`target_notional_usd / best_ask`. Default $50/trade. Tail buckets are fat-tailed (rare large losses) so per-trade size is small.

## 7. Risk rules
- `max_concurrent_positions` (default 50 — many small bets)
- Per-market cap = `target_notional_usd`

## 8. Failure modes
| Mode | Detection |
|---|---|
| Tail actually hits | Position resolves to NO outcome → we lose; expected ~5% of trades |
| Cluster of correlated tails (heat wave hits multiple buckets simultaneously) | Same-day P&L distribution shows clustered losses; mitigated by sizing |
| Wrong category classification | We trade non-weather markets that look weather-like; matrix categories will surface this |

## 9. References
- Public scout findings on `ColdMath` / weather-tail-selling on Polymarket weather markets

## 10. Validation plan
- Synthetic: fires on weather category in price band; ignores non-weather; respects adverse-print filter.
- Replay: ≥10 signals, win rate >85%, avg trade > 0.

## 11. Promotion criteria
Default platform thresholds, but tighten kill criteria — fat-tail strategies need stricter monitoring.

## 12. Kill criteria
- 30-day rolling PnL < −20% (a meaningful losing streak signals retail isn't mispricing this anymore)
- 7-day cluster: 5+ losses in a row (correlated tail event; pause manually until it passes)
