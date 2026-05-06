"""Tag: liquidity_bucket — thin / medium / thick by 24h volume."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.core.events import Trade


class LiquidityBucketTag:
    name: str = "liquidity_bucket"
    description: str = "thin (<$1k 24h vol), medium ($1k-10k), thick (>$10k)"

    def tag_trade(self, trade: Trade, context: dict[str, Any]) -> Any:
        vol = context.get("volume_24h_usd")
        if vol is None:
            return "unknown"
        try:
            v = Decimal(str(vol))
        except Exception:
            return "unknown"
        if v < Decimal("1000"):
            return "thin"
        if v < Decimal("10000"):
            return "medium"
        return "thick"


def plugin() -> LiquidityBucketTag:
    return LiquidityBucketTag()
