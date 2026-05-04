# whale_copy_eod — Strategy Design Document

> Status: implemented · replay_only
> Edge class: `copy` (haircut −20%)

---

## 1. Thesis
A small handful of pre-identified Polymarket wallets consistently produce profitable trades — typically slow-money political and weather plays where the edge survives without HFT-grade execution. Mirroring their public on-chain trades, with sized-down position copies and reasonable filters, captures a fraction of their alpha.

## 2. Mechanics
On each `ACTIVITY_TRADE` event:
1. Check if wallet is in `tracked_wallets` set
2. Check if `usd_value >= min_copy_usd` (skip dust)
3. Check `cooldown` — don't re-copy the same (wallet, market) within `wallet_market_cooldown_secs`
4. Mirror side (BUY → BUY, SELL → SELL) on the same `(market_id, asset_id)` with `size = whale_size * copy_ratio`
5. Cap size at `max_size_per_trade_usd`
6. Hold to resolution (no active exits)

The wallet list is seeded from `ANALYTICS_SHARP_WALLETS` env var (also used by the `counterparty_estimate` tag) plus a small starter pair (`coldmath`, `henrytheatmophd`).

## 3. Data dependencies
| Source | What | Required |
|---|---|---|
| Polymarket activity feed (`polymarket_activity`) | Wallet trades + redemptions | yes |
| Polymarket CLOB | Best ask for sizing the copy at fair price | helpful (fall-back to whale's price) |

## 4. Entry rules
```
WHEN event.type == ACTIVITY_TRADE
  AND payload.wallet IN tracked_wallets
  AND payload.usd_value >= min_copy_usd
  AND (wallet, market_id) cooldown elapsed
  AND open_copy_count < max_concurrent_positions
EMIT
  Signal(side = whale.side,
         asset_id = whale.asset_id,
         price = best_ask + buffer (or whale.price if no book),
         size = min(whale.size * copy_ratio, max_size_per_trade_usd / price))
```

## 5. Exit rules
Hold to resolution. The strategy tries to ride the whale's bet, not exit early.

## 6. Sizing logic
`size = min(whale_size * copy_ratio, max_size_per_trade_usd / price)`. Default `copy_ratio = 0.05` (5% of whale size) and `max_size_per_trade_usd = $200`. So a whale's $100k trade results in our $200; a whale's $1k trade results in our $50.

## 7. Risk rules
- `max_concurrent_positions`: 30 default
- `max_size_per_trade_usd` cap
- Wallet-market cooldown prevents stacking on the same wallet's repeated activity in one market

## 8. Failure modes
| Mode | Detection |
|---|---|
| Whale's edge doesn't transfer (their info advantage not relevant at our scale) | sustained negative PnL despite mirroring |
| Whale exits before we observe it (latency = 5–60s on activity feed polling) | systematic adverse fills; observe via post-fill 60s adverse moves |
| Whale was misidentified as profitable | per-wallet PnL drift downward; tag analysis surfaces this |
| Wallet identity churn (whale changes wallet, original goes silent) | gap in copy signals; manual list refresh required |

## 9. References
- Public scout findings: `coldmath` (weather tail-sells), `henrytheatmophd` (weather tail-buys), various political-leaning wallets

## 10. Validation plan
- Synthetic: fires only on tracked wallets; respects cooldown; respects size cap; ignores untracked wallets and below-threshold trades.
- Replay: ≥ 5 signals in 30-day window if any tracked wallet was active.

## 11. Promotion criteria
Default platform thresholds, plus a per-wallet PnL filter at promotion time — only graduate to live_full if the seed wallets show positive replay PnL.

## 12. Kill criteria
- 30-day rolling PnL < −15% of capital
- All tracked wallets net negative over 30 days (signals our seed list is bad)
