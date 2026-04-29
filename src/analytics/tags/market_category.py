"""Tag: market_category — politics / weather / sports / crypto-event / ..."""

from __future__ import annotations

from typing import Any

from src.core.events import Trade


class MarketCategoryTag:
    name: str = "market_category"
    description: str = "High-level market family (politics, weather, sports, crypto-event, esports, finance, pop-culture, uncategorized)"

    def tag_trade(self, trade: Trade, context: dict[str, Any]) -> Any:
        cat = context.get("market_category")
        if cat:
            return cat.lower()
        return "uncategorized"


def plugin() -> MarketCategoryTag:
    return MarketCategoryTag()
