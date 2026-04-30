# redemption_sniper — Decision Log

## 2026-04-29 · Initial implementation
- **Edge class `slow`**: 1-hour window means we never need fast execution. The −15% haircut reflects that.
- **Why an adverse-print filter**: catches the case where someone just sold heavily at a price below our target. If recent prints suggest the consensus is shifting, the "near-certain" thesis is broken — abstain.
- **Why fire on the asset at the high end of the range, not the paired low-end leg**: the market has already chosen a winner. We mirror that conviction rather than fading it. Buying NO at $0.01 (the paired leg) is the `weather_tail_buy` family, not redemption sniping.
- **Why hold-to-resolution and not active TP**: max upside is `1.00 - ask`, which is small enough that any active management would burn fees relative to expected profit. Just hold.
