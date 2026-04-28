"""Synthetic test strategy — fires deterministic signals for harness testing.

NOT a real strategy. Used solely by the integration test in
``tests/integration/test_fill_engine_e2e.py`` to drive the fill simulator
with predictable inputs.

The leading underscore on the folder keeps the plugin loader from picking
this up at runtime.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

from src.core.events import (
    EventType,
    MarketEvent,
    OrderType,
    Side,
    Signal,
)


class SyntheticStrategy:
    """Fires a buy signal on every BOOK_SNAPSHOT for a configured market."""

    name: str = "synthetic"
    edge_class: str = "directional"

    def __init__(
        self,
        target_market: str = "test-market",
        target_asset: str = "test-asset",
        sleeve_id: str = "synthetic_sleeve",
        config_id: str = "default",
        side: Side = Side.BUY,
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        size: Decimal = Decimal("10"),
    ) -> None:
        self.target_market = target_market
        self.target_asset = target_asset
        self.sleeve_id = sleeve_id
        self.config_id = config_id
        self.side = side
        self.order_type = order_type
        self.price = price
        self.size = size
        self.fired_count = 0

    def required_event_types(self) -> set[str]:
        return {EventType.BOOK_SNAPSHOT.value}

    def required_data_sources(self) -> set[str]:
        return {"polymarket_clob"}

    async def on_event(
        self,
        event: MarketEvent,
        state: dict[str, Any],
    ) -> list[Signal]:
        if event.event_type != EventType.BOOK_SNAPSHOT:
            return []
        if event.market_id != self.target_market or event.asset_id != self.target_asset:
            return []

        self.fired_count += 1
        return [
            Signal(
                signal_id=uuid4(),
                sleeve_id=self.sleeve_id,
                strategy_name=self.name,
                config_id=self.config_id,
                market_id=event.market_id,
                asset_id=event.asset_id,
                side=self.side,
                order_type=self.order_type,
                price=self.price,
                size=self.size,
                reason=f"synthetic-trigger-{self.fired_count}",
                ts_signal=event.ts,
            )
        ]


def plugin() -> SyntheticStrategy:
    return SyntheticStrategy()
