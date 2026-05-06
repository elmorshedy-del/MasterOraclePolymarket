"""maker_passive — place limits 1 tick inside best bid/ask on liquid markets.

V1: no active cancel-and-replace; relies on fill simulator's MISSED detection
and a fresh placement every place_interval_secs.

This is the strategy that most exercises the fill simulator's maker queue
logic — its replay vs live divergence is the canonical sim-quality signal.
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
class MakerPassiveParams:
    min_24h_volume_usd: float = 5000.0
    target_notional_usd: Decimal = Decimal("50")
    tick_size: Decimal = Decimal("0.01")           # default Polymarket tick
    min_spread_ticks: int = 2                       # require spread >= 2 ticks
    place_interval_secs: int = 60
    max_concurrent_positions: int = 50


class MakerPassive:
    name: str = "maker_passive"
    edge_class: str = "maker"

    def __init__(self, **params: Any) -> None:
        self.params = MakerPassiveParams(
            **{k: v for k, v in params.items() if k in MakerPassiveParams.__annotations__},
        )
        for f in ("target_notional_usd", "tick_size"):
            v = getattr(self.params, f)
            if not isinstance(v, Decimal):
                setattr(self.params, f, Decimal(str(v)))

    def required_event_types(self) -> set[str]:
        return {
            EventType.BOOK_SNAPSHOT.value,
            EventType.BOOK_DELTA.value,
            EventType.MARKET_META.value,
        }

    def required_data_sources(self) -> set[str]:
        return {"polymarket_clob", "polymarket_markets"}

    async def on_event(self, event: MarketEvent, state: dict[str, Any]) -> list[Signal]:
        if event.venue != "polymarket":
            return []

        if market_meta_cache.apply(state, event):
            return []
        if not book_state.apply(state, event):
            return []

        market_id = event.market_id
        asset_id = event.asset_id
        if market_id is None or asset_id is None:
            return []

        # Volume filter
        vol = market_meta_cache.volume_24h(state, market_id)
        if vol is None or vol < self.params.min_24h_volume_usd:
            return []

        bid = book_state.best_bid(state, asset_id)
        ask = book_state.best_ask(state, asset_id)
        if bid is None or ask is None:
            return []

        # Per-market tick size, with strategy-default fallback
        meta = market_meta_cache.get(state, market_id) or {}
        try:
            tick = Decimal(str(meta.get("tick_size") or self.params.tick_size))
        except Exception:
            tick = self.params.tick_size

        if (ask - bid) < tick * self.params.min_spread_ticks:
            return []

        # Cooldown: don't re-place on same (asset, side) within place_interval_secs
        last_placed: dict[tuple[str, str], Any] = state.setdefault("_last_placed", {})
        cooldown = timedelta(seconds=self.params.place_interval_secs)

        # Concurrency cap
        active: set[tuple[str, str, str]] = state.setdefault("_active_orders", set())
        if len(active) >= self.params.max_concurrent_positions:
            return []

        sleeve_id = state.get("sleeve_id", "")
        config_id = state.get("config_id", "default")

        signals: list[Signal] = []
        mid = (bid + ask) / Decimal(2)
        size = (self.params.target_notional_usd / mid).quantize(Decimal("0.01"))
        if size <= 0:
            return []

        for side, side_str in ((Side.BUY, "buy"), (Side.SELL, "sell")):
            key = (asset_id, side_str)
            last = last_placed.get(key)
            if last is not None and (event.ts - last) < cooldown:
                continue

            if side == Side.BUY:
                price = (bid + tick).quantize(Decimal("0.0001"))
                if price >= ask:
                    continue
            else:
                price = (ask - tick).quantize(Decimal("0.0001"))
                if price <= bid:
                    continue

            last_placed[key] = event.ts
            active.add((market_id, asset_id, side_str))

            signals.append(Signal(
                signal_id=uuid4(),
                sleeve_id=sleeve_id,
                strategy_name=self.name,
                config_id=config_id,
                market_id=market_id,
                asset_id=asset_id,
                side=side,
                order_type=OrderType.LIMIT,
                price=price,
                size=size,
                reason=f"maker_passive: bid={bid:.4f} ask={ask:.4f} place {side_str}@{price:.4f}",
                ts_signal=event.ts,
                metadata={"bid_at_signal": str(bid), "ask_at_signal": str(ask), "tick": str(tick)},
            ))
        return signals


def plugin() -> MakerPassive:
    return MakerPassive()
