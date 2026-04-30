"""basket_arb — multi-outcome arb. Fires N BUY signals when Σ asks < threshold.

Generalizes cross_outcome_arb to N legs. Replay-deterministic via
``_lib.book_state``.
"""

from __future__ import annotations

from dataclasses import dataclass
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
class BasketArbParams:
    min_legs: int = 3
    min_edge_bps: int = 200             # require ≥2.00% gross edge (more legs = more execution risk)
    max_sum_threshold: Decimal = Decimal("0.98")
    max_size_per_leg_usd: Decimal = Decimal("100")
    price_buffer_bps: int = 50
    max_concurrent_positions: int = 10


class BasketArb:
    name: str = "basket_arb"
    edge_class: str = "pure_arb"

    def __init__(self, **params: Any) -> None:
        self.params = BasketArbParams(
            **{k: v for k, v in params.items() if k in BasketArbParams.__annotations__},
        )
        if not isinstance(self.params.max_sum_threshold, Decimal):
            self.params.max_sum_threshold = Decimal(str(self.params.max_sum_threshold))
        if not isinstance(self.params.max_size_per_leg_usd, Decimal):
            self.params.max_size_per_leg_usd = Decimal(str(self.params.max_size_per_leg_usd))

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
        if market_id is None:
            return []

        # Track all asset_ids seen for this market
        market_assets: dict[str, set[str]] = state.setdefault("_market_assets", {})
        if event.asset_id is not None:
            market_assets.setdefault(market_id, set()).add(event.asset_id)

        active_arbs: set[str] = state.setdefault("active_arbs", set())
        if market_id in active_arbs:
            return []
        if len(active_arbs) >= self.params.max_concurrent_positions:
            return []

        legs = market_assets.get(market_id, set())
        if len(legs) < self.params.min_legs:
            return []

        # Cross-check vs MARKET_META if we have it (don't fire if we know there
        # are more legs than we've seen)
        meta = market_meta_cache.get(state, market_id)
        if meta is not None:
            expected = len(meta.get("asset_ids", []) or [])
            if expected > 0 and len(legs) < expected:
                return []

        # Compute sum of asks; bail if any leg has no ask
        asset_to_ask: dict[str, Decimal] = {}
        for asset_id in sorted(legs):
            ask = book_state.best_ask(state, asset_id)
            if ask is None:
                return []
            asset_to_ask[asset_id] = ask

        sum_asks = sum(asset_to_ask.values(), Decimal(0))
        if sum_asks > self.params.max_sum_threshold:
            return []

        gross_edge_bps = int((Decimal("1") - sum_asks) * Decimal("10000"))
        if gross_edge_bps < self.params.min_edge_bps:
            return []

        active_arbs.add(market_id)

        sleeve_id = state.get("sleeve_id", "")
        config_id = state.get("config_id", "default")
        buffer = Decimal(self.params.price_buffer_bps) / Decimal("10000")

        reason = (
            f"basket_arb: legs={len(legs)} sum_asks={sum_asks:.4f} "
            f"edge_bps={gross_edge_bps}"
        )

        signals: list[Signal] = []
        for asset_id, ask in asset_to_ask.items():
            size = (self.params.max_size_per_leg_usd / ask).quantize(Decimal("0.01"))
            price = (ask + buffer).quantize(Decimal("0.0001"))
            if size <= 0:
                continue
            signals.append(Signal(
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
                reason=reason,
                ts_signal=event.ts,
                metadata={
                    "leg_count": len(asset_to_ask),
                    "gross_edge_bps": gross_edge_bps,
                },
            ))
        return signals


def plugin() -> BasketArb:
    return BasketArb()
