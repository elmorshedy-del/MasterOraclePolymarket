"""Win rate — fraction of trades with positive P&L."""

from __future__ import annotations

from src.core.events import Trade


class WinRateMetric:
    name: str = "win_rate"
    higher_is_better: bool = True

    def compute(self, trades: list[Trade]) -> float:
        total = 0
        wins = 0
        for t in trades:
            pnl = t.pnl_after_haircut if t.pnl_after_haircut is not None else t.pnl
            if pnl is None:
                continue
            total += 1
            if pnl > 0:
                wins += 1
        return wins / total if total > 0 else 0.0


def plugin() -> WinRateMetric:
    return WinRateMetric()
