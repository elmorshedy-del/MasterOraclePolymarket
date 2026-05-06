"""avg_slippage_bps — average measured slippage across a sleeve's trades.

This metric replaces the literature-based −22% realism haircut as the
headline measure of "gap to real money." Slippage is computed at fill time
in event_replay.py:_fill_taker by walking the actual book ladder and
comparing weighted-avg fill price to the book mid at signal time.
"""

from __future__ import annotations

from src.core.events import Trade


class AvgSlippageBpsMetric:
    name: str = "avg_slippage_bps"
    higher_is_better: bool = False  # less slippage is better

    def compute(self, trades: list[Trade]) -> float:
        bps_values: list[float] = []
        for t in trades:
            if t.slippage_bps is not None:
                bps_values.append(float(t.slippage_bps))
        return sum(bps_values) / len(bps_values) if bps_values else 0.0


def plugin() -> AvgSlippageBpsMetric:
    return AvgSlippageBpsMetric()
