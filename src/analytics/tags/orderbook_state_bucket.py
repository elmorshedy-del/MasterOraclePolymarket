"""Tag: orderbook_state_bucket — book thickness at entry."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.core.events import Trade


class OrderbookStateBucketTag:
    name: str = "orderbook_state_bucket"
    description: str = "Book thickness at entry — thin (<$500 at TOB), medium ($500-2000), thick (>$2000)"

    def tag_trade(self, trade: Trade, context: dict[str, Any]) -> Any:
        book = context.get("book_at_entry")
        if book is None:
            return "unknown"

        bid = book.best_bid()
        ask = book.best_ask()
        if bid is None or ask is None:
            return "one_sided"

        # Approximate USD depth at TOB = (bid_size + ask_size) * mid
        try:
            mid = (bid.price + ask.price) / Decimal(2)
            tob_usd = (bid.size + ask.size) * mid
        except Exception:  # noqa: BLE001
            return "unknown"

        if tob_usd < Decimal("500"):
            return "thin"
        if tob_usd < Decimal("2000"):
            return "medium"
        return "thick"


def plugin() -> OrderbookStateBucketTag:
    return OrderbookStateBucketTag()
