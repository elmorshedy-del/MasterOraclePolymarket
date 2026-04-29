"""Average trade P&L."""

from __future__ import annotations

from src.core.events import Trade


class AvgTradeMetric:
    name: str = "avg_trade"
    higher_is_better: bool = True

    def compute(self, trades: list[Trade]) -> float:
        pnls = [
            float(t.pnl_after_haircut if t.pnl_after_haircut is not None else (t.pnl or 0))
            for t in trades
            if t.pnl is not None or t.pnl_after_haircut is not None
        ]
        return sum(pnls) / len(pnls) if pnls else 0.0


def plugin() -> AvgTradeMetric:
    return AvgTradeMetric()
