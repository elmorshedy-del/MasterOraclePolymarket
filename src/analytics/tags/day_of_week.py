"""Tag: day_of_week — 0 (Mon) through 6 (Sun)."""

from __future__ import annotations

from typing import Any

from src.core.events import Trade


class DayOfWeekTag:
    name: str = "day_of_week"
    description: str = "ISO weekday (0=Mon, 6=Sun)"

    def tag_trade(self, trade: Trade, context: dict[str, Any]) -> Any:
        return trade.entry_ts.weekday()


def plugin() -> DayOfWeekTag:
    return DayOfWeekTag()
