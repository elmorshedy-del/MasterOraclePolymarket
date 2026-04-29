# cross_outcome_arb — Strategy Design Document

> Status: implemented · replay_only (awaiting historical data)
> Author: elmorshedydel
> Edge class: `pure_arb`

---

## 1. Thesis

In a Polymarket binary market, the YES and NO tokens must redeem to a combined $1.00. Whenever the sum of best asks across both outcomes is strictly less than $1.00 (after fees and slippage), buying both legs locks in a guaranteed profit at resolution.

## 2. Mechanics

For every binary Polymarket market, maintain a per-asset best-ask view derived from CLOB events. On each book update, recompute:

```
sum_asks = best_ask(YES) + best_ask(NO)
gross_edge_bps = (1.00 - sum_asks) * 10_000
```

If `gross_edge_bps >= min_edge_bps` AND `sum_asks <= max_sum_threshold`, fire **two** signals:

1. BUY `asset_id_yes` at `best_ask(YES) + price_buffer_bps/10000`
2. BUY `asset_id_no` at `best_ask(NO) + price_buffer_bps/10000`

Both legs are MARKET-equivalent LIMIT orders (limit set just above ask) sized so total notional ≤ `max_size_per_leg_usd × 2`.

The position closes itself at market resolution — both YES and NO redeem to either $1 (for the winner) or $0 (for the loser). Combined payout = $1 across the pair, regardless of outcome.

## 3. Data dependencies

| Source | What we read | Required? |
|---|---|---|
| Polymarket CLOB websocket | book snapshots + price_change deltas for binary markets | yes |
| Polymarket markets metadata | asset_id pairing within each market | yes (bootstrap) |

**No external data feeds.** The strategy is fully replayable from `market_events` history.

## 4. Entry rules

```
WHEN both legs of a binary market have a current best_ask
  AND sum_asks <= max_sum_threshold (default 0.99)
  AND gross_edge_bps >= min_edge_bps (default 100, i.e. 1%)
  AND no open position already exists for this market
  AND open_positions < max_concurrent_positions
EMIT
  Signal(BUY, asset_id_yes, LIMIT @ best_ask_yes + price_buffer, size = max_size / best_ask_yes)
  Signal(BUY, asset_id_no,  LIMIT @ best_ask_no  + price_buffer, size = max_size / best_ask_no)
WITH
  reason = "cross_outcome_arb: sum_asks=0.97 edge_bps=300 yes=0.50 no=0.47"
```

## 5. Exit rules

- **Hold to resolution.** Both legs together redeem to exactly $1.00.
- **No active exits.** The strategy does not TP, stop, or rebalance.
- **Edge case**: if only one leg fills (broken arb), the position becomes directional. The strategy logs this but does NOT close the open leg — the platform's position tracker holds it through resolution. This is the dominant V1 risk; see §8.

## 6. Sizing logic

Per-leg size is computed in tokens, not USD:

```
target_notional = min(max_size_per_leg_usd, capital_remaining / 2)
size_tokens = target_notional / best_ask
```

If `target_notional / best_ask` exceeds `max_concurrent_positions × per-position cap`, the trade is skipped to preserve risk caps. Per-trade notional is hard-capped at `max_size_per_leg_usd` regardless of available capital.

## 7. Risk rules

| Rule | Default | Notes |
|---|---|---|
| Max concurrent positions (paired arbs) | 25 | Per-sleeve cap |
| Max exposure per market | `max_size_per_leg_usd × 2` | Hard cap, no rebalancing |
| Max correlated exposure | n/a | Each market resolves independently |
| Reject if size > 10% of resting depth | enforced by fill-sim preflight | Realism flag: `would_have_moved_market` |

## 8. Failure modes

| Mode | Cause | Real-time detection |
|---|---|---|
| **Broken arb (one-leg fill)** | Price moves between leg-1 fill and leg-2 attempt; or one venue/asset rejects | `paper_orders.status` shows one filled, other cancelled/missed; sleeve has odd-sided position open |
| **Slippage eats edge** | Both fills happen but at worse prices than book snapshot | `pnl_after_haircut < 0` despite gross edge > 0 at signal time |
| **Implausible fill** | Sim says we filled at a price the market never traded at | `realism_flag = implausible` (caught by FillValidator at +5min) |
| **Late resolution** | Market settles slowly or disputes; capital tied up longer than expected | `time_to_resolution_bucket > 7d` average increases |
| **Adverse selection (rare for arb)** | The other side knows something — e.g., resolution news in flight | Picked-off rate climbs in matrix; mostly irrelevant for true math arb |

## 9. References

- Shleifer & Vishny (1997), *The Limits of Arbitrage*, Journal of Finance — friction-cost framework
- Polymarket subgraph + CLOB docs: https://docs.polymarket.com/
- Internal: scout findings on basket-arb sums (the multi-outcome variant lives in `basket_arb`)

## 10. Validation plan

### Synthetic tests (`tests/test_synthetic.py`)
- Both-legs sum below threshold → emits exactly 2 signals (BUY YES + BUY NO)
- Sum at exactly threshold → emits 0 signals (boundary inclusive of threshold; we require strict edge)
- Sum above threshold → emits 0 signals
- Only one leg seen so far → emits 0 signals (waiting for pair)
- Sum drops below threshold then rises again → second event above threshold does not re-emit
- Existing open position for the same market → does not re-arb

### Replay tests (`tests/test_replay.py`)
- Run against last 30 days of recorded events. Assert:
  - At least 5 signals emitted across the window (very loose; actual fire rate depends on market)
  - All emitted trade pairs have `pnl_after_haircut > -gas_cost*4` (no catastrophic losses)
  - No `realism_flag = implausible` rate above 5%

### Live observation criteria
- Signals fire at expected rate per `gross_edge_bps` distribution
- Maker fill rate trends matter LESS here because all orders are limit-just-above-ask (effectively taker)
- Watch for the broken-arb counter; it must stay below 5% of fired pairs

## 11. Promotion criteria

| Gate | Required |
|---|---|
| `replay_only` → `live_log` | ≥ 30 signals in 30-day replay; replay realized PnL > 0; broken-arb rate < 10% |
| `live_log` → `live_signal` | ≥ 14 days live; live signal rate matches replay-predicted ±30% |
| `live_signal` → `live_full` | ≥ 14 days; simulated fill rate ≥ 60% on both legs; broken-arb rate < 5%; implausible rate < 2% |
| `live_full` ongoing | Maintain Sharpe > 0 over rolling 30 days, broken-arb rate < 8%, capital_remaining > 80% of starting |

## 12. Kill criteria

- 30-day rolling realized PnL falls below −15% of starting capital
- Broken-arb rate exceeds 15% over a 7-day window (signals execution layer is failing systematically)
- Implausible flag rate exceeds 10% (signals fill simulator mismatch with reality — pause and recalibrate)
- 60-day Sharpe < 0
