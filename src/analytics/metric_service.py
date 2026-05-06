"""Metric application service.

Auto-discovers Metric plugins and computes them over a list of Trades.
Used by the API for sleeve scorecards and matrix-cell stats.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.core import plugin_loader
from src.core.events import Trade
from src.core.interfaces import Metric

logger = logging.getLogger(__name__)


REPO_ROOT = Path(__file__).resolve().parents[2]


class MetricService:
    def __init__(self) -> None:
        plugins = plugin_loader.discover_all(REPO_ROOT)
        self.metrics: list[Metric] = [p.instance for p in plugins if p.kind == "metric"]
        self.metrics.sort(key=lambda m: m.name)

    def compute_all(self, trades: list[Trade]) -> dict[str, float]:
        out: dict[str, float] = {}
        for m in self.metrics:
            try:
                out[m.name] = m.compute(trades)
            except Exception:
                logger.exception("metric %s raised", m.name)
                out[m.name] = float("nan")
        return out
