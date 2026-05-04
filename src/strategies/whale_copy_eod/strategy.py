"""whale_copy_eod — mirror profitable wallets via activity feed.

Replay-deterministic: state is built purely from ACTIVITY_TRADE events plus
optional CLOB snapshots for fair-price sizing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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


def _seed_wallets() -> set[str]:
    raw = os.environ.get("ANALYTICS_SHARP_WALLETS", "")
    seeded = {w.strip().lower() for w in raw.split(",") if w.strip()}
    seeded.update({"coldmath", "henrytheatmophd"})
    return seeded


@dataclass
class WhaleCopyParams:
    tracked_wallets: set[str] = field(default_factory=_seed_wallets)
    min_copy_usd: Decimal = Decimal("100")
    copy_ratio: Decimal = Decimal("0.05")
    max_size_per_trade_usd: Decimal = Decimal("200")
    price_buffer_bps: int = 50
    wallet_market_cooldown_secs: int = 600
    max_concurrent_positions: int = 30


class WhaleCopyEod:
    name: str = "whale_copy_eod"
    edge_class: str = "copy"

    def __init__(self, **params: Any) -> None:
        kw = {k: v for k, v in params.items() if k in WhaleCopyParams.__annotations__}
        if "tracked_wallets" in kw and isinstance(kw["tracked_wallets"], list):
            kw["tracked_wallets"] = {str(w).lower() for w in kw["tracked_wallets"]}
        self.params = WhaleCopyParams(**kw)
        for f in ("min_copy_usd", "copy_ratio", "max_size_per_trade_usd"):
            v = getattr(self.params, f)
            if not isinstance(v, Decimal):
                setattr(self.params, f, Decimal(str(v)))

    def required_event_types(self) -> set[str]:
        return {
            EventType.ACTIVITY_TRADE.value,
            EventType.BOOK_SNAPSHOT.value,
            EventType.BOOK_DELTA.value,
        }

    def required_data_sources(self) -> set[str]:
        return {"polymarket_activity"}

    async def on_event(self, event: MarketEvent, state: dict[str, Any]) -> list[Signal]:
        if event.venue != "polymarket":
            return []

        # Maintain a book view so we can size at the current best ask
        book_state.apply(state, event)

        if event.event_type != EventType.ACTIVITY_TRADE:
            return []

        market_id = event.market_id
        asset_id = event.asset_id
        if market_id is None or asset_id is None:
            return []

        payload = event.payload or {}
        wallet = (payload.get("wallet") or "").lower()
        if not wallet or wallet not in self.params.tracked_wallets:
            return []

        # USD value filter
        usd_raw = payload.get("usd_value")
        try:
            usd_value = Decimal(str(usd_raw)) if usd_raw is not None else None
        except Exception:  # noqa: BLE001
            usd_value = None
        if usd_value is None or usd_value < self.params.min_copy_usd:
            return []

        # Side
        side_raw = (payload.get("side") or "").upper()
        if side_raw not in ("BUY", "SELL"):
            return []
        whale_side = Side.BUY if side_raw == "BUY" else Side.SELL

        # Whale's traded size (tokens)
        size_raw = payload.get("size")
        try:
            whale_size = Decimal(str(size_raw)) if size_raw is not None else None
        except Exception:  # noqa: BLE001
            whale_size = None
        if whale_size is None or whale_size <= 0:
            return []

        # Cooldown — don't re-copy the same (wallet, market) too quickly
        cooldown_map: dict[tuple[str, str], Any] = state.setdefault("_wallet_cooldown", {})
        last = cooldown_map.get((wallet, market_id))
        if last is not None and (event.ts - last) < timedelta(seconds=self.params.wallet_market_cooldown_secs):
            return []

        # Concurrent cap
        active: set[tuple[str, str]] = state.setdefault("_active_copies", set())
        if len(active) >= self.params.max_concurrent_positions:
            return []

        # Fair-price sizing — prefer current book, else fall back to whale's price
        ask = book_state.best_ask(state, asset_id)
        whale_price_raw = payload.get("price")
        try:
            whale_price = Decimal(str(whale_price_raw)) if whale_price_raw is not None else None
        except Exception:  # noqa: BLE001
            whale_price = None

        ref_price = ask or whale_price
        if ref_price is None or ref_price <= 0:
            return []

        # Apply size scaling: copy_ratio of whale size, capped by USD-budget
        scaled_size = whale_size * self.params.copy_ratio
        usd_capped_size = self.params.max_size_per_trade_usd / ref_price
        size = min(scaled_size, usd_capped_size).quantize(Decimal("0.01"))
        if size <= 0:
            return []

        buffer = Decimal(self.params.price_buffer_bps) / Decimal("10000")
        price = (ref_price + buffer).quantize(Decimal("0.0001"))

        cooldown_map[(wallet, market_id)] = event.ts
        active.add((wallet, market_id))

        sleeve_id = state.get("sleeve_id", "")
        config_id = state.get("config_id", "default")

        return [Signal(
            signal_id=uuid4(),
            sleeve_id=sleeve_id,
            strategy_name=self.name,
            config_id=config_id,
            market_id=market_id,
            asset_id=asset_id,
            side=whale_side,
            order_type=OrderType.LIMIT,
            price=price,
            size=size,
            reason=f"whale_copy_eod: wallet={wallet} side={side_raw} usd=${usd_value:.0f}",
            ts_signal=event.ts,
            metadata={
                "wallet": wallet,
                "whale_usd_value": str(usd_value),
                "whale_size": str(whale_size),
                "copy_ratio": str(self.params.copy_ratio),
                "ref_price": str(ref_price),
            },
        )]


def plugin() -> WhaleCopyEod:
    return WhaleCopyEod()
