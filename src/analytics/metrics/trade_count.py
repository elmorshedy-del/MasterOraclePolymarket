"""Trade count."""

from __future__ import annotations

from src.core.events import Trade


class TradeCountMetric:
    name: str = "trade_count"
    higher_is_better: bool = True   # neutral, but more = more signal in matrix

    def compute(self, trades: list[Trade]) -> float:
        return float(len(trades))


def plugin() -> TradeCountMetric:
    return TradeCountMetric()
