"""Tag: time_to_resolution_bucket — how far from market close at entry."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from src.core.events import Trade


class TimeToResolutionBucketTag:
    name: str = "time_to_resolution_bucket"
    description: str = "<1h, 1-24h, 1-7d, >7d"

    def tag_trade(self, trade: Trade, context: dict[str, Any]) -> Any:
        end = context.get("end_time")
        if not isinstance(end, datetime):
            return "unknown"

        remaining = end - trade.entry_ts
        if remaining < timedelta(hours=1):
            return "<1h"
        if remaining < timedelta(hours=24):
            return "1-24h"
        if remaining < timedelta(days=7):
            return "1-7d"
        return ">7d"


def plugin() -> TimeToResolutionBucketTag:
    return TimeToResolutionBucketTag()
