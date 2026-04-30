# basket_arb — Decision Log

## 2026-04-29 · Initial implementation
- **Why min_legs default = 3**: 2-leg arb is already covered by cross_outcome_arb. basket_arb earns its keep on N≥3 markets.
- **Why higher edge floor (200bps) than cross_outcome (100bps)**: more legs = more cumulative slippage and higher leg-failure probability. The extra cushion accounts for it.
- **Why MARKET_META cross-check**: prevents the dangerous "fire on partial leg set, miss the rest, pay $1 for a basket worth $0.30" scenario. If meta says 5 outcomes and we've only seen 3, we wait.
- **Why no support for sum > 1 (short the basket)**: Polymarket doesn't allow shorting a non-binary leg. The complement basket trick works for binary only.
