# whale_copy_eod — Decision Log

## 2026-04-30 · Initial implementation
- **Why "reactive copy" not "EOD net position"**: simpler. Reactive copies show up in our paper book at roughly the same time the whale's trade prints, so we ride their bets in lockstep. EOD net-position copying is a Phase 7+ enhancement (requires building a per-wallet position model).
- **Why `copy_ratio = 0.05` default**: 5% of whale size means we're rarely big enough to be the marginal liquidity provider on the other side, which would distort their edge. Capacity tests in Phase 7+ may push this up if data supports.
- **Why USD cap on top of ratio**: a single whale's $50k trade at copy_ratio = 0.05 = $2,500. Without cap that concentrates risk. Cap of $200 keeps each copy within sleeve risk envelope.
- **Why fall back to whale's price for sizing when no book**: activity feed sometimes arrives before our CLOB has a snapshot for that asset. Prefer to size at the whale's print over skipping the trade.
- **Edge class `copy`**: new in Phase 6 (haircut −20%). The risks are not the same as pure_arb (math), maker (queue), latency_sensitive (speed), or directional (idea quality). Copy risk is "the alpha doesn't generalize" — slow to manifest but real.
