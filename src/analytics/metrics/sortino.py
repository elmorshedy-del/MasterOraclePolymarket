"""Annualized Sortino — Sharpe variant using downside deviation."""

from __future__ import annotations

import math

from src.core.events import Trade

_ANNUALIZATION = math.sqrt(2520)


class SortinoMetric:
    name: str = "sortino"
    higher_is_better: bool = True

    def compute(self, trades: list[Trade]) -> float:
        pnls = [
            float(t.pnl_after_haircut if t.pnl_after_haircut is not None else (t.pnl or 0))
            for t in trades
            if t.pnl is not None or t.pnl_after_haircut is not None
        ]
        if len(pnls) < 2:
            return 0.0
        mean = sum(pnls) / len(pnls)
        downside = [x for x in pnls if x < 0]
        if not downside:
            return float("inf") if mean > 0 else 0.0
        dvar = sum(x ** 2 for x in downside) / len(pnls)
        dstd = math.sqrt(dvar)
        if dstd == 0:
            return 0.0
        return (mean / dstd) * _ANNUALIZATION


def plugin() -> SortinoMetric:
    return SortinoMetric()
