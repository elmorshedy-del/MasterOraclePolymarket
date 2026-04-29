"""Tag: time_of_day_bucket — UTC hour bucket at entry."""

from __future__ import annotations

from typing import Any

from src.core.events import Trade


class TimeOfDayBucketTag:
    name: str = "time_of_day_bucket"
    description: str = "UTC hour bucket — 0-6, 6-12, 12-18, 18-24"

    def tag_trade(self, trade: Trade, context: dict[str, Any]) -> Any:
        h = trade.entry_ts.hour
        if h < 6:
            return "0-6"
        if h < 12:
            return "6-12"
        if h < 18:
            return "12-18"
        return "18-24"


def plugin() -> TimeOfDayBucketTag:
    return TimeOfDayBucketTag()
