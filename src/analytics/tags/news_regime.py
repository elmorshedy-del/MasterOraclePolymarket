"""Tag: news_regime — calm / news_event / post_event based on news activity near entry."""

from __future__ import annotations

from typing import Any

from src.core.events import Trade


class NewsRegimeTag:
    name: str = "news_regime"
    description: str = "calm (no news in 5min before entry), news_event (1-3 items), post_event (>3 items)"

    def tag_trade(self, trade: Trade, context: dict[str, Any]) -> Any:
        n = context.get("pre_entry_news_count", 0)
        if not isinstance(n, int):
            return "unknown"
        if n == 0:
            return "calm"
        if n <= 3:
            return "news_event"
        return "post_event"


def plugin() -> NewsRegimeTag:
    return NewsRegimeTag()
