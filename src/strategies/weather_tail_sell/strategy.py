"""weather_tail_sell — buy NO at $0.95+ on weather-category tail buckets.

V1 heuristic: no forecast data; relies on price-band filter only. Replay-
deterministic via _lib helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
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
class WeatherTailSellParams:
    min_price: Decimal = Decimal("0.95")
    max_price: Decimal = Decimal("0.99")
    target_notional_usd: Decimal = Decimal("50")
    price_buffer_bps: int = 50
    recent_adverse_threshold: Decimal = Decimal("0.02")
    recent_window_secs: int = 300
    max_concurrent_positions: int = 50
    category_keywords: tuple[str, ...] = ("weather",)


class WeatherTailSell:
    name: str = "weather_tail_sell"
    edge_class: str = "tail"

    def __init__(self, **params: Any) -> None:
        kw = {k: v for k, v in params.items() if k in WeatherTailSellParams.__annotations__}
        # Tuples in YAML come back as lists
        if "category_keywords" in kw and isinstance(kw["category_keywords"], list):
            kw["category_keywords"] = tuple(kw["category_keywords"])
        self.params = WeatherTailSellParams(**kw)
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

        if event.event_type == EventType.TRADE_PRINT and event.asset_id is not None:
            try:
                price = Decimal(str(event.payload.get("price")))
            except (TypeError, ValueError):
                return []
            recent = state.setdefault("_recent_prints", {}).setdefault(event.asset_id, [])
            recent.append((event.ts, price))
            cutoff = event.ts - timedelta(seconds=600)
            state["_recent_prints"][event.asset_id] = [(t, p) for (t, p) in recent if t >= cutoff]
            return []

        if not book_state.apply(state, event):
            return []

        market_id = event.market_id
        asset_id = event.asset_id
        if market_id is None or asset_id is None:
            return []

        # Category gate
        cat = market_meta_cache.category(state, market_id) or ""
        if not any(kw in cat for kw in self.params.category_keywords):
            return []

        ask = book_state.best_ask(state, asset_id)
        if ask is None:
            return []
        if ask < self.params.min_price or ask > self.params.max_price:
            return []

        # Adverse-print filter
        recent = state.get("_recent_prints", {}).get(asset_id, [])
        cutoff = event.ts - timedelta(seconds=self.params.recent_window_secs)
        threshold = ask - self.params.recent_adverse_threshold
        if any(p <= threshold and t >= cutoff for (t, p) in recent):
            return []

        active: set[tuple[str, str]] = state.setdefault("_active_tails", set())
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
            side=Side.BUY,                   # buy NO @ high price = "sell the tail"
            order_type=OrderType.LIMIT,
            price=price,
            size=size,
            reason=f"weather_tail_sell: ask={ask:.4f} cat={cat}",
            ts_signal=event.ts,
            metadata={"ask_at_signal": str(ask), "category": cat},
        )]


def plugin() -> WeatherTailSell:
    return WeatherTailSell()
