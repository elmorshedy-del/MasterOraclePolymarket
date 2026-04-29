"""Max drawdown ($) over a sequence of trades."""

from __future__ import annotations

from src.core.events import Trade


class MaxDrawdownMetric:
    name: str = "max_drawdown"
    higher_is_better: bool = False

    def compute(self, trades: list[Trade]) -> float:
        # Sort by exit ts so equity-curve order is correct
        sorted_trades = sorted(
            (t for t in trades if t.pnl_after_haircut is not None or t.pnl is not None),
            key=lambda t: t.exit_ts or t.entry_ts,
        )
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in sorted_trades:
            pnl = float(t.pnl_after_haircut if t.pnl_after_haircut is not None else (t.pnl or 0))
            equity += pnl
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
        return max_dd


def plugin() -> MaxDrawdownMetric:
    return MaxDrawdownMetric()
