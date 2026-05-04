# momentum_orderbook — Decision Log

## 2026-04-30 · Initial implementation
- **Why edge class `latency_sensitive` (−28% haircut)**: book-imbalance signals decay fast — by the time we sleep through the latency budget, the imbalance has often already resolved. Strategy lab `latency_ms` override is the canonical test for whether this strategy actually has edge.
- **Why bullish trades the SAME asset, bearish trades the PAIRED asset**: Polymarket has no native short. A bearish call is expressed by buying the OTHER outcome.
- **Why min_tob_depth_usd filter**: tiny TOB sizes give imbalance ratios that are statistical noise (e.g., 1 vs 2 contracts is 67/33 imbalance but means nothing).
- **Why per-(market, asset) cooldown not per-market**: a market can have legitimate bullish AND bearish signals on different legs at different times. The cooldown protects against spam from the same leg, not from cross-leg alternation.
- **Why hold to resolution**: same as mean_revert. The TP exit is a Phase 6+ enhancement; for now the strategy expresses an implicit directional bet.
