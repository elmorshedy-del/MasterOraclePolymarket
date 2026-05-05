"""Canonical event and data types.

All venues normalize into these types. All strategies consume these types.
The fill simulator emits ``Fill`` and ``Trade`` instances. The position tracker
consumes ``Trade`` instances.

Keep this module free of venue-specific or strategy-specific logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


# ---------------------------------------------------------------------------
# Primitive enums
# ---------------------------------------------------------------------------


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order intent at the strategy layer.

    The fill simulator decides actual taker vs maker behavior based on price
    relative to top-of-book. ``MARKET`` is always taker; ``LIMIT`` may rest
    or cross.
    """

    MARKET = "market"
    LIMIT = "limit"


class FillType(str, Enum):
    TAKER = "taker"
    MAKER_FAST = "maker_fast"   # filled within 10s of placement
    MAKER_SLOW = "maker_slow"   # filled after 10s
    MISSED = "missed"            # placed but never filled (price walked away or expired)


class RealismFlag(str, Enum):
    CLEAN = "clean"
    WOULD_HAVE_MOVED_MARKET = "would_have_moved_market"
    THIN_MARKET = "thin_market"
    IMPLAUSIBLE = "implausible"
    PICKED_OFF = "picked_off"


class RuntimeMode(str, Enum):
    REPLAY_ONLY = "replay_only"
    LIVE_LOG = "live_log"
    LIVE_SIGNAL = "live_signal"
    LIVE_FULL = "live_full"


class EventType(str, Enum):
    """Categories of normalized market events the platform consumes."""

    BOOK_SNAPSHOT = "book_snapshot"
    BOOK_DELTA = "book_delta"
    TRADE_PRINT = "trade_print"
    TICK_SIZE_CHANGE = "tick_size_change"
    MARKET_META = "market_meta"                # one-shot metadata event for a market
    MARKET_RESOLVED = "market_resolved"
    MARKET_PAUSED = "market_paused"
    ACTIVITY_TRADE = "activity_trade"          # public wallet trade observed via activity feed
    ACTIVITY_REDEMPTION = "activity_redemption"
    NEWS_ITEM = "news_item"
    EXTERNAL_PRICE = "external_price"          # crypto spot, perp, weather, etc.


# ---------------------------------------------------------------------------
# Market metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketMeta:
    """Static-ish metadata about a market across the platform's lifecycle."""

    market_id: str                  # platform-internal canonical id
    venue: str                      # "polymarket" | "kalshi" | ...
    venue_market_id: str            # the venue's own id (slug, conditionId, etc.)
    asset_ids: tuple[str, ...]      # token ids / outcome ids
    title: str
    category: str                   # politics, weather, sports, crypto-event, ...
    subcategory: str | None
    end_time: datetime | None       # market resolution deadline (may be unknown)
    tick_size: Decimal              # min price increment
    tags_extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Order book state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PriceLevel:
    price: Decimal
    size: Decimal


@dataclass
class OrderBook:
    """Live in-memory order book reconstructed from event stream."""

    market_id: str
    asset_id: str
    bids: list[PriceLevel] = field(default_factory=list)   # sorted desc by price
    asks: list[PriceLevel] = field(default_factory=list)   # sorted asc by price
    last_update_ts: datetime | None = None

    def best_bid(self) -> PriceLevel | None:
        return self.bids[0] if self.bids else None

    def best_ask(self) -> PriceLevel | None:
        return self.asks[0] if self.asks else None

    def mid(self) -> Decimal | None:
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        return (bid.price + ask.price) / Decimal(2)

    def spread(self) -> Decimal | None:
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        return ask.price - bid.price

    def taker_consumable_depth(self, side: Side, price: Decimal) -> Decimal:
        """Total OPPOSING-side liquidity a taker order can consume up to ``price``.

        For a BUY taker: sum asks with price <= our limit.
        For a SELL taker: sum bids with price >= our limit.

        This is the metric the realism preflight cares about ("would my order
        eat 10% of available liquidity?"). Distinct from
        ``depth_at_or_better`` which is the maker-perspective queue lookup.
        """
        total = Decimal(0)
        if side == Side.BUY:
            for level in self.asks:
                if level.price <= price:
                    total += level.size
                else:
                    break
        else:
            for level in self.bids:
                if level.price >= price:
                    total += level.size
                else:
                    break
        return total

    def depth_at_or_better(self, side: Side, price: Decimal) -> Decimal:
        """Total resting size at-or-better than a given price (MAKER perspective).

        For a buy (we'd be a bid), better-than means strictly higher. For a
        sell, better-than means strictly lower. Used by RestingMaker for
        queue-position math; NOT for taker preflight (use
        :meth:`taker_consumable_depth` for that).
        """
        total = Decimal(0)
        if side == Side.BUY:
            for level in self.bids:
                if level.price >= price:
                    total += level.size
                else:
                    break
        else:
            for level in self.asks:
                if level.price <= price:
                    total += level.size
                else:
                    break
        return total


# ---------------------------------------------------------------------------
# Market events (the unified stream)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketEvent:
    """Unified event the platform passes around.

    Specific event types put structured data in ``payload``. Strategies and
    the fill simulator inspect ``event_type`` and key into ``payload``.
    """

    event_id: UUID
    event_type: EventType
    market_id: str | None
    asset_id: str | None
    venue: str
    ts: datetime
    payload: dict[str, Any]

    @staticmethod
    def make(
        event_type: EventType,
        venue: str,
        payload: dict[str, Any],
        market_id: str | None = None,
        asset_id: str | None = None,
        ts: datetime | None = None,
    ) -> MarketEvent:
        return MarketEvent(
            event_id=uuid4(),
            event_type=event_type,
            market_id=market_id,
            asset_id=asset_id,
            venue=venue,
            ts=ts or datetime.now(tz=timezone.utc),
            payload=payload,
        )


# ---------------------------------------------------------------------------
# Strategy outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Signal:
    """A strategy's intent — pre-execution. Carries the *reason* for an order.

    Signals are first-class and stored even if the order never fills, so we
    can analyze signal quality independently of fill quality.
    """

    signal_id: UUID
    sleeve_id: str
    strategy_name: str
    config_id: str
    market_id: str
    asset_id: str
    side: Side
    order_type: OrderType
    price: Decimal | None              # required for LIMIT, ignored for MARKET
    size: Decimal
    reason: str                        # human-readable; logged for analysis
    ts_signal: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Order:
    """An order in flight, post-signal, pre-fill.

    Carries the latency-injected timestamps so the fill simulator can decide
    when the order "arrives" at the venue.
    """

    order_id: UUID
    signal_id: UUID
    sleeve_id: str
    market_id: str
    asset_id: str
    side: Side
    order_type: OrderType
    price: Decimal | None
    size: Decimal
    ts_signal: datetime
    ts_placed: datetime                # post-latency, the simulated venue-arrival ts
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Fill:
    """A simulated fill emitted by the fill simulator.

    A single Order may produce 0, 1, or many Fills (partial fills supported).
    Fills aggregate up to a Trade in the position tracker.
    """

    fill_id: UUID
    order_id: UUID
    sleeve_id: str
    market_id: str
    asset_id: str
    side: Side
    price: Decimal
    size: Decimal
    fill_type: FillType
    ts_filled: datetime
    realism_flag: RealismFlag
    gas_cost: Decimal = Decimal("0.10")
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Trade:
    """A completed paper trade — entry through exit.

    This is what gets tagged with the full analytics dimensions and pivoted
    in the dashboard.
    """

    trade_id: UUID
    sleeve_id: str
    strategy_name: str
    config_id: str
    market_id: str
    asset_id: str
    side: Side
    entry_price: Decimal
    entry_size: Decimal
    entry_ts: datetime
    exit_price: Decimal | None
    exit_size: Decimal | None
    exit_ts: datetime | None
    pnl: Decimal | None
    pnl_after_haircut: Decimal | None
    realism_flag: RealismFlag
    fill_type: FillType
    tags: dict[str, Any] = field(default_factory=dict)
