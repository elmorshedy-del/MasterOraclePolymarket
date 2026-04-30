# maker_passive — Decision Log

## 2026-04-29 · V1 implementation
- **Why no active cancel/replace**: keeps the strategy interface unchanged. The platform's fill simulator handles MISSED detection (book walking past us). We re-emit on a cooldown so a stale resting order is never our only quote for long.
- **Why two signals (bid + ask) per cycle**: simulates two-sided quoting. The spread captured per round-trip = `ask_inside - bid_inside`, which is `spread - 2 * tick`.
- **Volume filter (`min_24h_volume_usd`)**: avoids placing on illiquid markets where adverse selection is far worse and the queue model is least reliable.
- **`min_spread_ticks: 2`**: if we'd be inside-the-best by 1 tick, that puts our two orders at adjacent prices — there's no spread to capture. Require at least 2 ticks of spread before quoting.
- **Edge class `maker`** → −38% haircut. The biggest among any strategy in V1; reflects the high uncertainty around real-world fill rates and adverse selection.
