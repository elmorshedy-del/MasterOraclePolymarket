"""Capacity estimate: P&L per dollar of size deployed.

Coarse first-pass capacity number — finer capacity stress tests via
replay variants come in Phase 4+.
"""

from __future__ import annotations

from src.core.events import Trade


class CapacityEstimateMetric:
    name: str = "capacity_estimate"
    higher_is_better: bool = True

    def compute(self, trades: list[Trade]) -> float:
        total_pnl = 0.0
        total_notional = 0.0
        for t in trades:
            pnl = t.pnl_after_haircut if t.pnl_after_haircut is not None else t.pnl
            if pnl is None:
                continue
            total_pnl += float(pnl)
            total_notional += float(t.entry_price) * float(t.entry_size)
        return total_pnl / total_notional if total_notional > 0 else 0.0


def plugin() -> CapacityEstimateMetric:
    return CapacityEstimateMetric()
