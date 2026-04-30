# weather_tail_buy — Strategy Design Document

> Status: implemented (heuristic V1) · replay_only
> Edge class: `tail`

---

## 1. Thesis (sign-inverted twin of weather_tail_sell)
The same structural retail mispricing that makes far-tail buckets overpriced makes near-consensus buckets *underpriced* at the very low end. Buying YES at $0.01–$0.05 on consensus-adjacent buckets captures the residual when consensus holds — payoff 20–100× the entry cost when correct.

## 2. Mechanics (V1 heuristic)
For weather-category markets:
- If `best_ask` is in `[min_price, max_price]` (default $0.01–$0.05)
- Buy YES at LIMIT just-above-ask, sized small (`target_notional_usd` default $25).

Without forecast data, the V1 heuristic fires on any weather-category leg with a low enough price; it counts on the broad observation that low-priced legs near consensus carry more probability than the price implies.

## 3. Data dependencies
Same as weather_tail_sell. Forecast integration is Phase 6+.

## 4. Entry rules
```
WHEN market_category contains 'weather' (case-insensitive)
  AND min_price <= best_ask <= max_price
  AND no recent supportive adverse-print (helps avoid catching falling knives)
EMIT Signal(BUY, asset_id, LIMIT @ ask + buffer, size = target_notional / ask)
```

## 5. Exit rules
Hold to resolution.

## 6. Sizing logic
Tiny — `target_notional_usd / best_ask` with default $25 / $0.05 = 500 tokens. The strategy is ALL about the long tail of large wins; small per-trade size is the right shape.

## 7. Risk rules
- `max_concurrent_positions` (default 100 — many tiny bets across many markets)
- Per-market cap = `target_notional_usd`

## 8. Failure modes
| Mode | Detection |
|---|---|
| Most positions resolve to 0 (the tail did NOT hit) | Win rate is intentionally low (5–15%); profit comes from concentrated wins |
| All positions cluster on the same outcome (e.g., heat wave) | Same-day P&L distribution shows clustered wins or losses |
| Mispriced by other reason (the tail is genuinely 0% probability) | Negative replay PnL despite high signal count |

## 9. References
- Public scout findings on `HenryTheAtmoPhD` / weather-tail-buying pattern

## 10. Validation plan
- Synthetic: fires in price band; ignores non-weather; respects adverse-print filter.
- Replay: ≥30 signals (more than tail_sell because there are many cheap legs); win rate 5–15%; positive aggregate PnL.

## 11. Promotion criteria
Default platform thresholds. Conservative variant uses tighter price band ($0.01–$0.02).

## 12. Kill criteria
- 60-day rolling PnL < −15% (longer window because the strategy is high-variance)
- Win rate falls below 2% (almost all bets losing means our basic premise is wrong)
