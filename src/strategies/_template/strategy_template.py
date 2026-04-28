"""Starting-point implementation skeleton for a new strategy.

Copy this to ``src/strategies/<your_name>/strategy.py`` and fill in the
methods. The plugin loader expects a top-level ``plugin()`` factory that
returns an instance.

Do NOT import this file directly elsewhere — it's a template. The leading
underscore on ``_template`` keeps the plugin loader from picking it up.
"""

from __future__ import annotations

from typing import Any

from src.core.events import MarketEvent, Signal


class TemplateStrategy:
    """Replace this docstring with your strategy's one-line thesis."""

    name: str = "template"
    edge_class: str = "directional"   # pure_arb | maker | latency_sensitive | directional | copy | tail | slow

    def required_event_types(self) -> set[str]:
        return {"book_snapshot", "book_delta", "trade_print"}

    def required_data_sources(self) -> set[str]:
        return {"polymarket_clob"}

    async def on_event(
        self,
        event: MarketEvent,
        state: dict[str, Any],
    ) -> list[Signal]:
        # 1. Check filters: is this an event the strategy cares about?
        # 2. Compute signal predicate.
        # 3. If predicate fires, emit Signal(s).
        return []


def plugin() -> TemplateStrategy:
    return TemplateStrategy()
