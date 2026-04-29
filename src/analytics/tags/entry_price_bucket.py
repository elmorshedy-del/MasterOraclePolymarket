"""Tag: entry_price_bucket — coarse price region at entry."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.core.events import Trade


BUCKETS = (
    (Decimal("0.05"), "<$0.05"),
    (Decimal("0.25"), "$0.05-0.25"),
    (Decimal("0.75"), "$0.25-0.75"),
    (Decimal("0.95"), "$0.75-0.95"),
    (Decimal("1.01"), ">$0.95"),
)


class EntryPriceBucketTag:
    name: str = "entry_price_bucket"
    description: str = "Coarse price region at entry"

    def tag_trade(self, trade: Trade, context: dict[str, Any]) -> Any:
        price = trade.entry_price
        for upper, label in BUCKETS:
            if price < upper:
                return label
        return ">$0.95"


def plugin() -> EntryPriceBucketTag:
    return EntryPriceBucketTag()
