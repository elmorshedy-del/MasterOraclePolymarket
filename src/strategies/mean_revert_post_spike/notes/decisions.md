# mean_revert_post_spike — Decision Log

## 2026-04-30 · Initial implementation
- **Why fade by BUYING the paired asset, not selling the spiked one**: Polymarket doesn't allow short selling. The fade has to be expressed by buying the OTHER outcome.
- **Why the paired asset must be in [0.10, 0.80]**: at the extremes, edge is dominated by other forces (resolution near-certainty at 0.95+, or basket-arb territory at <0.05). The middle is where mean reversion has historically held best.
- **Why "lowest paired ask" picking**: in multi-outcome markets there can be more than one paired asset. Choosing the cheapest gives us the highest payout-per-dollar and the most "fade conviction" (the most-priced-down candidate).
- **Why hold-to-resolution and not TP**: the platform doesn't have fill-driven exits in V1. Once we buy at low price and the market mean-reverts, we'd ideally TP at +X bps. Phase 6+ can add that machinery; for now it's a directional bet.
