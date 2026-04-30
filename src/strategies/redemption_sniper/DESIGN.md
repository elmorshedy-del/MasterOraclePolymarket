# redemption_sniper — Strategy Design Document

> Status: implemented · replay_only
> Edge class: `slow` (haircut −15%; very low friction, plenty of execution time)

---

## 1. Thesis
Polymarket markets often trade at $0.97–$0.99 in the final hour before resolution when the outcome is essentially decided. Buying YES at this range, when the market is genuinely converging on resolution, captures 1–3% in minutes-to-hours with very low risk if the filter is strict.

## 2. Mechanics
For each market within `time_to_resolution_window` of its end_time:
- If `min_price <= best_ask <= max_price`
- AND no recent adverse trade prints (defined: no print at-or-below `best_ask − recent_adverse_threshold` in last `recent_window_secs`)
- Fire one BUY signal at LIMIT just-above-ask, sized by `target_notional_usd`.

Position holds to resolution; redeems to $1 (winner) or $0 (loser).

## 3. Data dependencies
| Source | What | Required |
|---|---|---|
| Polymarket CLOB | book + trade prints | yes |
| Polymarket markets meta | `end_time` per market | yes |

## 4. Entry rules
```
WHEN end_time - now <= time_to_resolution_window (default 1h)
  AND min_price <= best_ask <= max_price (defaults 0.97 / 0.99)
  AND no trade print at best_ask - 0.01 or below in last 60s
  AND no open position on this market for this sleeve
EMIT Signal(BUY, asset_id_yes, LIMIT @ best_ask + buffer, size = target_notional / best_ask)
```

The strategy fires only on the asset that is at the top of the price range, not on both legs. We're betting the market is correctly converging on YES; if NO is at $0.97+, we'd snipe NO instead. The strategy chooses the more "decided" leg based on its asks alone.

## 5. Exit rules
Hold to resolution. No active exits.

## 6. Sizing logic
Target `target_notional_usd` per trade (default $200). Tokens = notional / best_ask. With ask in [0.97, 0.99], 200 USD ≈ 200–206 tokens.

## 7. Risk rules
- `max_concurrent_positions` (default 25)
- `max_per_market_usd` matches `target_notional_usd`
- Skips markets without `MARKET_META` (no end_time means no time filter)

## 8. Failure modes
| Mode | Detection |
|---|---|
| Resolution upset (the rare "decided" outcome flips) | post-resolution PnL = −$0.97. Inevitable cost; we accept ~1% expected loss rate to capture the 99% wins |
| Late resolution / dispute | position tied up beyond expected — we don't act, but capital is locked |
| Adverse selection (a sharp knows the resolution will flip) | `recent_adverse_threshold` filter catches some; not all |
| End_time wrong/stale in meta | rare; would cause us to skip valid opportunities (false negative, not loss) |

## 9. References
- Retail-redemption inefficiency is well-documented across binary prediction markets. The "$0.99 problem" — markets that should be $1.00 trading at $0.97–0.99 because of opportunity cost — is the canonical example.

## 10. Validation plan
- Synthetic: fires inside window + price band; ignores outside; respects adverse-print filter.
- Replay: ≥10 signals on aggressive config; resolved trades show majority winners.

## 11. Promotion criteria
Default platform thresholds. Conservative variant (min_price 0.98, target $100) for first live run.

## 12. Kill criteria
- 30-day rolling PnL < −10% (this strategy should produce mostly small wins; sustained losses mean filter is wrong)
- Adverse-flip rate > 5% (filter is too loose)
