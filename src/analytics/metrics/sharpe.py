"""Annualized Sharpe ratio over per-trade P&L."""

from __future__ import annotations

import math

from src.core.events import Trade

# We treat each trade as an independent observation and annualize against
# an assumed 252 trading days × ~10 trades/day = 2520 observations/yr as a
# coarse default. For sleeves with very different fire rates this should be
# overridden via the metric's params, but the platform-default fits most.
_ANNUALIZATION = math.sqrt(2520)


class SharpeMetric:
    name: str = "sharpe"
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
        var = sum((x - mean) ** 2 for x in pnls) / (len(pnls) - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        if std == 0:
            return 0.0
        return (mean / std) * _ANNUALIZATION


def plugin() -> SharpeMetric:
    return SharpeMetric()
