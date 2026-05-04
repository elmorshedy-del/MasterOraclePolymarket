"""mean_revert_post_spike — fade large rapid moves on Polymarket binary markets.

After detecting a spike on one asset, BUY the *paired* asset (which has
dropped). Holds to resolution since the platform doesn't yet support
fill-driven exits.
"""

from __future__ import annotations

from collections import deque
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
from src.strategies._lib import book_state


@dataclass
class MeanRevertParams:
    window_secs: int = 120                  # rolling window for spike detection
    spike_threshold_pct: Decimal = Decimal("0.10")    # 10% move
    min_tradeable_price: Decimal = Decimal("0.10")    # paired asset price floor
    max_tradeable_price: Decimal = Decimal("0.80")    # paired asset price ceiling
    target_notional_usd: Decimal = Decimal("50")
    price_buffer_bps: int = 100
    fade_cooldown_secs: int = 600
    max_concurrent_positions: int = 30


class MeanRevertPostSpike:
    name: str = "mean_revert_post_spike"
    edge_class: str = "directional"

    def __init__(self, **params: Any) -> None:
        self.params = MeanRevertParams(
            **{k: v for k, v in params.items() if k in MeanRevertParams.__annotations__},
        )
        for f in ("spike_threshold_pct", "min_tradeable_price", "max_tradeable_price",
                  "target_notional_usd"):
            v = getattr(self.params, f)
            if not isinstance(v, Decimal):
                setattr(self.params, f, Decimal(str(v)))

    def required_event_types(self) -> set[str]:
        return {EventType.BOOK_SNAPSHOT.value, EventType.BOOK_DELTA.value}

    def required_data_sources(self) -> set[str]:
        return {"polymarket_clob"}

    async def on_event(self, event: MarketEvent, state: dict[str, Any]) -> list[Signal]:
        if event.venue != "polymarket":
            return []
        if not book_state.apply(state, event):
            return []

        market_id = event.market_id
        asset_id = event.asset_id
        if market_id is None or asset_id is None:
            return []

        # Track asset_ids per market for paired lookup
        market_assets: dict[str, set[str]] = state.setdefault("_market_assets", {})
        market_assets.setdefault(market_id, set()).add(asset_id)

        # Track price history per asset
        history: dict[str, deque] = state.setdefault("_price_history", {})
        mid = book_state.mid(state, asset_id)
        if mid is None:
            return []

        h = history.setdefault(asset_id, deque())
        h.append((event.ts, mid))
        cutoff = event.ts - timedelta(seconds=self.params.window_secs)
        while h and h[0][0] < cutoff:
            h.popleft()
        if len(h) < 2:
            return []

        oldest_ts, oldest_price = h[0]
        if oldest_price <= 0:
            return []
        pct_change = (mid - oldest_price) / oldest_price
        if abs(pct_change) < self.params.spike_threshold_pct:
            return []

        # Direction: spike up on this asset → fade by buying a paired asset
        # whose price should have dropped. Find any other asset_id in same
        # market with price in tradeable band.
        legs = market_assets.get(market_id, set()) - {asset_id}
        if not legs:
            return []

        # Cooldown
        cooldowns: dict[str, Any] = state.setdefault("_fade_cooldown", {})
        last = cooldowns.get(market_id)
        if last is not None and (event.ts - last) < timedelta(seconds=self.params.fade_cooldown_secs):
            return []

        # Concurrent cap
        active: set[str] = state.setdefault("_active_fades", set())
        if market_id in active:
            return []
        if len(active) >= self.params.max_concurrent_positions:
            return []

        # Pick the most-tradeable paired asset (lowest ask in band)
        candidates: list[tuple[str, Decimal]] = []
        for pair_asset in sorted(legs):
            pair_ask = book_state.best_ask(state, pair_asset)
            if pair_ask is None:
                continue
            if pair_ask < self.params.min_tradeable_price or pair_ask > self.params.max_tradeable_price:
                continue
            candidates.append((pair_asset, pair_ask))
        if not candidates:
            return []

        # Pick the candidate with the lowest ask (most attractive entry)
        pair_asset, pair_ask = min(candidates, key=lambda x: x[1])

        cooldowns[market_id] = event.ts
        active.add(market_id)

        sleeve_id = state.get("sleeve_id", "")
        config_id = state.get("config_id", "default")
        buffer = Decimal(self.params.price_buffer_bps) / Decimal("10000")
        price = (pair_ask + buffer).quantize(Decimal("0.0001"))
        size = (self.params.target_notional_usd / pair_ask).quantize(Decimal("0.01"))
        if size <= 0:
            return []

        return [Signal(
            signal_id=uuid4(),
            sleeve_id=sleeve_id,
            strategy_name=self.name,
            config_id=config_id,
            market_id=market_id,
            asset_id=pair_asset,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=price,
            size=size,
            reason=(
                f"mean_revert_post_spike: spiked={asset_id[:8]} "
                f"pct={float(pct_change):.3f} fade={pair_asset[:8]}@{pair_ask:.4f}"
            ),
            ts_signal=event.ts,
            metadata={
                "spiked_asset": asset_id,
                "spiked_pct": str(pct_change),
                "fade_asset": pair_asset,
                "fade_ask": str(pair_ask),
            },
        )]


def plugin() -> MeanRevertPostSpike:
    return MeanRevertPostSpike()
