"""Total P&L (after haircut)."""

from __future__ import annotations

from src.core.events import Trade


class TotalPnLMetric:
    name: str = "total_pnl"
    higher_is_better: bool = True

    def compute(self, trades: list[Trade]) -> float:
        total = 0.0
        for t in trades:
            pnl = t.pnl_after_haircut if t.pnl_after_haircut is not None else t.pnl
            if pnl is not None:
                total += float(pnl)
        return total


def plugin() -> TotalPnLMetric:
    return TotalPnLMetric()
