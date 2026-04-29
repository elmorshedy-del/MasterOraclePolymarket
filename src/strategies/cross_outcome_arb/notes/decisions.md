# cross_outcome_arb — Decision Log

Append-only record of design + parameter decisions, with rationale.

---

## 2026-04-29 · Initial implementation

- **Why `pure_arb` edge class** (haircut −18%): the gross edge is mathematical;
  frictions are gas + minor slippage on the buffer-above-ask price. There is
  no maker-fill or adverse-selection component because both legs are taken
  immediately at LIMIT-just-above-ask.
- **Why limit-just-above-ask instead of pure MARKET orders**: lets the fill
  simulator surface partial-fill behavior cleanly. A pure MARKET order would
  fill at any price; the LIMIT cap at `ask + price_buffer` keeps the realism
  flag honest if the book moved against us during the latency window.
- **Why `max_sum_threshold = 0.99` for default**: leaves ~$0.01 of room for
  gas ($0.10 across both legs ≈ 0.05¢ on a $200 trade) plus modest slippage.
  Tighter (0.97) is the conservative variant.
- **Why no exit logic**: both legs together always redeem to $1.00. Active
  exits would only burn fees. Hold-to-resolution is the strategy.
- **Why `active_arbs` per market in state**: prevents stacking multiple arb
  positions on the same market when the sum keeps moving below threshold —
  one arb per market until it resolves.
- **Why two separate Signals (not one combined)**: the platform's signal /
  order / fill / position pipeline is per-asset. Splitting cleanly lets the
  position tracker, fill simulator, and realism flagger work without any
  special-casing for paired strategies.
