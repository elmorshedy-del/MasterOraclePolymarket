"""momentum_orderbook — trade in direction of TOB depth imbalance.

Replay-deterministic via _lib.book_state. Holds to resolution.
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
from src.strategies._lib import book_state


@dataclass
class MomentumOrderbookParams:
    bullish_threshold: Decimal = Decimal("0.75")
    bearish_threshold: Decimal = Decimal("0.25")
    min_price: Decimal = Decimal("0.20")
    max_price: Decimal = Decimal("0.80")
    min_tob_depth_usd: Decimal = Decimal("200")
    target_notional_usd: Decimal = Decimal("40")
    price_buffer_bps: int = 100
    cooldown_secs: int = 120
    max_concurrent_positions: int = 60


class MomentumOrderbook:
    name: str = "momentum_orderbook"
    edge_class: str = "latency_sensitive"

    def __init__(self, **params: Any) -> None:
        self.params = MomentumOrderbookParams(
            **{k: v for k, v in params.items() if k in MomentumOrderbookParams.__annotations__},
        )
        for f in ("bullish_threshold", "bearish_threshold", "min_price", "max_price",
                  "min_tob_depth_usd", "target_notional_usd"):
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

        # Track asset_ids per market
        market_assets: dict[str, set[str]] = state.setdefault("_market_assets", {})
        market_assets.setdefault(market_id, set()).add(asset_id)

        ask = book_state.best_ask(state, asset_id)
        bid = book_state.best_bid(state, asset_id)
        ask_sz = book_state.best_ask_size(state, asset_id)
        bid_sz = book_state.best_bid_size(state, asset_id)
        if ask is None or bid is None or ask_sz is None or bid_sz is None:
            return []

        mid = (ask + bid) / Decimal(2)
        if mid < self.params.min_price or mid > self.params.max_price:
            return []

        # Depth filter — TOB must have meaningful USD depth
        tob_depth_usd = (ask_sz + bid_sz) * mid
        if tob_depth_usd < self.params.min_tob_depth_usd:
            return []

        total = ask_sz + bid_sz
        if total <= 0:
            return []
        imbalance = bid_sz / total

        bullish = imbalance >= self.params.bullish_threshold
        bearish = imbalance <= self.params.bearish_threshold
        if not (bullish or bearish):
            return []

        # Determine which asset to BUY
        target_asset: str | None = None
        target_ask: Decimal | None = None
        if bullish:
            target_asset, target_ask = asset_id, ask
        else:
            # Bearish: BUY the paired asset (we can't short)
            legs = market_assets.get(market_id, set()) - {asset_id}
            for pair in sorted(legs):
                pair_ask = book_state.best_ask(state, pair)
                if pair_ask is None:
                    continue
                if pair_ask < self.params.min_price or pair_ask > self.params.max_price:
                    continue
                target_asset, target_ask = pair, pair_ask
                break

        if target_asset is None or target_ask is None:
            return []

        # Cooldown is the only throttle for momentum: positions resolve when
        # the underlying market resolves, and the test contract is "after the
        # cooldown expires the strategy may re-fire on the same pair."
        cooldowns: dict[tuple[str, str], Any] = state.setdefault("_mom_cooldowns", {})
        last = cooldowns.get((market_id, target_asset))
        if last is not None and (event.ts - last) < timedelta(seconds=self.params.cooldown_secs):
            return []

        # Coarse concurrent-pair counter — central platform-level risk caps
        # are enforced separately in the runner.
        active: set[tuple[str, str]] = state.setdefault("_active_mom", set())
        if len(active) >= self.params.max_concurrent_positions:
            return []

        cooldowns[(market_id, target_asset)] = event.ts
        active.add((market_id, target_asset))

        sleeve_id = state.get("sleeve_id", "")
        config_id = state.get("config_id", "default")
        buffer = Decimal(self.params.price_buffer_bps) / Decimal("10000")
        price = (target_ask + buffer).quantize(Decimal("0.0001"))
        size = (self.params.target_notional_usd / target_ask).quantize(Decimal("0.01"))
        if size <= 0:
            return []

        direction = "bullish" if bullish else "bearish"
        return [Signal(
            signal_id=uuid4(),
            sleeve_id=sleeve_id,
            strategy_name=self.name,
            config_id=config_id,
            market_id=market_id,
            asset_id=target_asset,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=price,
            size=size,
            reason=(
                f"momentum_orderbook: imbalance={float(imbalance):.3f} "
                f"dir={direction} target={target_asset[:8]}@{target_ask:.4f}"
            ),
            ts_signal=event.ts,
            metadata={
                "imbalance": str(imbalance),
                "direction": direction,
                "tob_depth_usd": str(tob_depth_usd),
                "trigger_asset": asset_id,
                "target_asset": target_asset,
            },
        )]


def plugin() -> MomentumOrderbook:
    return MomentumOrderbook()
