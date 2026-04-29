"""Tag: market_subcategory — finer-grained category (e.g., weather/nyc/temp, nfl/regular-season)."""

from __future__ import annotations

from typing import Any

from src.core.events import Trade


class MarketSubcategoryTag:
    name: str = "market_subcategory"
    description: str = "Finer-grained classification (weather/nyc/temp, election/2026, fed/rate-decision)"

    def tag_trade(self, trade: Trade, context: dict[str, Any]) -> Any:
        sub = context.get("market_subcategory")
        return sub.lower() if isinstance(sub, str) else None


def plugin() -> MarketSubcategoryTag:
    return MarketSubcategoryTag()
