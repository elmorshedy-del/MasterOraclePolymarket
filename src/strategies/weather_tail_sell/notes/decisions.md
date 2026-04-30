# weather_tail_sell — Decision Log

## 2026-04-29 · V1 heuristic implementation
- Skipping forecast integration in V1 — defer to Phase 6 once we can pipe NOAA / Visual Crossing into the live runner. The price-only heuristic captures the "obviously far tail" case.
- Edge class `tail` — fat-tailed strategy. Sized small ($50/trade default) on purpose; it produces many small wins and rare large losses.
- Category-keyword filter is substring match (`weather` matches `weather/nyc/temp`); will refine to subcategory match once we have a richer market-meta taxonomy.
