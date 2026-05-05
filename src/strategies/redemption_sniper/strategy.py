"""redemption_sniper — buy near-certain markets at the $0.97-0.99 range.

Replay-deterministic: needs MARKET_META for end_time. Filters on TRADE_PRINT
events to avoid sniping when an adverse print just happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
from src.strategies._lib import book_state, market_meta_cache


@dataclass
class RedemptionSniperParams:
    time_to_resolution_window_secs: int = 3600         # 1 hour
    min_price: Decimal = Decimal("0.97")
    max_price: Decimal = Decimal("0.99")
    target_notional_usd: Decimal = Decimal("200")
    price_buffer_bps: int = 25
    recent_adverse_threshold: Decimal = Decimal("0.01")
    recent_window_secs: int = 60
    max_concurrent_positions: int = 25


class RedemptionSniper:
    name: str = "redemption_sniper"
    edge_class: str = "slow"

    def __init__(self, **params: Any) -> None:
        self.params = RedemptionSniperParams(
            **{k: v for k, v in params.items() if k in RedemptionSniperParams.__annotations__},
        )
        for f in ("min_price", "max_price", "target_notional_usd", "recent_adverse_threshold"):
            v = getattr(self.params, f)
            if not isinstance(v, Decimal):
                setattr(self.params, f, Decimal(str(v)))

    def required_event_types(self) -> set[str]:
        return {
            EventType.BOOK_SNAPSHOT.value,
            EventType.BOOK_DELTA.value,
            EventType.TRADE_PRINT.value,
            EventType.MARKET_META.value,
        }

    def required_data_sources(self) -> set[str]:
        return {"polymarket_clob", "polymarket_markets"}

    async def on_event(self, event: MarketEvent, state: dict[str, Any]) -> list[Signal]:
        if event.venue != "polymarket":
            return []

        if market_meta_cache.apply(state, event):
            return []

        # Track recent adverse prints
        if event.event_type == EventType.TRADE_PRINT and event.asset_id is not None:
            from src.strategies._lib.parsing import safe_decimal
            price = safe_decimal(event.payload.get("price"))
            if price is not None:
                recent = state.setdefault("_recent_prints", {}).setdefault(event.asset_id, [])
                recent.append((event.ts, price))
                # Keep last 10 minutes only
                cutoff = event.ts - timedelta(seconds=600)
                state["_recent_prints"][event.asset_id] = [
                    (t, p) for (t, p) in recent if t >= cutoff
                ]
            return []

        # Update the in-strategy book
        if not book_state.apply(state, event):
            return []

        market_id = event.market_id
        asset_id = event.asset_id
        if market_id is None or asset_id is None:
            return []

        # Need market meta for end_time
        end = market_meta_cache.end_time(state, market_id)
        if end is None:
            return []

        # Time filter
        now = event.ts
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if (end - now).total_seconds() > self.params.time_to_resolution_window_secs:
            return []
        if end <= now:
            return []  # past resolution; no point sniping

        ask = book_state.best_ask(state, asset_id)
        if ask is None:
            return []
        if ask < self.params.min_price or ask > self.params.max_price:
            return []

        # Adverse-print filter
        recent = state.get("_recent_prints", {}).get(asset_id, [])
        cutoff = now - timedelta(seconds=self.params.recent_window_secs)
        threshold = ask - self.params.recent_adverse_threshold
        if any(p <= threshold and t >= cutoff for (t, p) in recent):
            return []

        # Position cap
        active: set[tuple[str, str]] = state.setdefault("_active_snipes", set())
        if (market_id, asset_id) in active:
            return []
        if len(active) >= self.params.max_concurrent_positions:
            return []

        active.add((market_id, asset_id))

        sleeve_id = state.get("sleeve_id", "")
        config_id = state.get("config_id", "default")
        buffer = Decimal(self.params.price_buffer_bps) / Decimal("10000")
        price = (ask + buffer).quantize(Decimal("0.0001"))
        size = (self.params.target_notional_usd / ask).quantize(Decimal("0.01"))
        if size <= 0:
            return []

        return [Signal(
            signal_id=uuid4(),
            sleeve_id=sleeve_id,
            strategy_name=self.name,
            config_id=config_id,
            market_id=market_id,
            asset_id=asset_id,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=price,
            size=size,
            reason=f"redemption_sniper: ask={ask:.4f} t-end={(end - now).total_seconds():.0f}s",
            ts_signal=event.ts,
            metadata={
                "secs_to_end": (end - now).total_seconds(),
                "ask_at_signal": str(ask),
            },
        )]


def plugin() -> RedemptionSniper:
    return RedemptionSniper()
