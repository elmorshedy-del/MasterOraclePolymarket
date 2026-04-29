"""Profit factor = gross wins / gross losses."""

from __future__ import annotations

from src.core.events import Trade


class ProfitFactorMetric:
    name: str = "profit_factor"
    higher_is_better: bool = True

    def compute(self, trades: list[Trade]) -> float:
        gross_win = 0.0
        gross_loss = 0.0
        for t in trades:
            pnl = t.pnl_after_haircut if t.pnl_after_haircut is not None else t.pnl
            if pnl is None:
                continue
            v = float(pnl)
            if v > 0:
                gross_win += v
            else:
                gross_loss += -v
        if gross_loss == 0:
            return float("inf") if gross_win > 0 else 0.0
        return gross_win / gross_loss


def plugin() -> ProfitFactorMetric:
    return ProfitFactorMetric()
