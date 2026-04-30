# weather_tail_buy — Decision Log

## 2026-04-29 · V1 heuristic implementation
- Mirror of weather_tail_sell, sign-inverted. Same caveats about forecast integration.
- Tiny per-trade size ($25 default) because the strategy is high-variance: most bets resolve to $0, a few resolve to $1 → 20–100× the entry.
- Adverse-print filter is opposite-direction here: a print at-or-below $0.005 means the market is pricing this as "near-zero", which is bearish (we don't want to buy what's converging to worthless).
