"""Tier 2 fill simulator — event-tape replay with queue tracking.

See DESIGN.md §4 for the algorithm.

Lifecycle:
  - submit(order, book): apply pre-flight realism filter; for taker orders,
    walk the book and emit a Fill synchronously; for maker orders, register
    a RestingMaker and return [] (fills come via on_event).
  - on_event(event, book): for every CLOB event, update each resting maker
    order. Trade prints at-or-through our price decrement queue; when queue
    hits zero, fill us at our price. Walk-away events emit MISSED markers.
  - cancel(order_id): remove a resting order without emitting a fill.

The simulator does NOT update the order book itself. The venue adapter does
that. The simulator only READS the book.

All fills carry realism flags so downstream analysis can distinguish clean
fills from would-have-moved-the-market trades.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from src.core.config import LatencyModel
from src.core.events import (
    EventType,
    Fill,
    FillType,
    MarketEvent,
    Order,
    OrderBook,
    OrderType,
    RealismFlag,
    Side,
)
from src.execution._resting import (
    DEFAULT_CANCEL_DECAY,
    RestingMaker,
)

logger = logging.getLogger(__name__)


# Pre-flight thresholds (DESIGN.md §4)
WOULD_MOVE_MARKET_PCT = Decimal("0.10")    # order > 10% of resting depth at price
THIN_MARKET_SPREAD = Decimal("0.03")       # spread > 3¢
DEFAULT_GAS_COST = Decimal("0.10")


class EventReplayFillSimulator:
    """Tier 2 fill simulator. Default for V1."""

    name: str = "event_replay"

    def __init__(
        self,
        latency: LatencyModel | None = None,
        gas_cost: Decimal = DEFAULT_GAS_COST,
        cancel_decay: Decimal = DEFAULT_CANCEL_DECAY,
    ) -> None:
        self.latency = latency or LatencyModel()
        self.gas_cost = gas_cost
        self.cancel_decay = cancel_decay

        self._resting: dict[UUID, RestingMaker] = {}

        # Telemetry
        self.taker_fills: int = 0
        self.maker_fills: int = 0
        self.missed_fills: int = 0
        self.would_have_moved_market: int = 0
        self.thin_market_flags: int = 0

    # -----------------------------------------------------------------------
    # FillSimulator interface
    # -----------------------------------------------------------------------

    async def submit(self, order: Order, book: OrderBook) -> list[Fill]:
        flags = self._preflight(order, book)

        if order.order_type == OrderType.MARKET or self._crosses_book(order, book):
            fill = self._fill_taker(order, book, flags)
            if fill is not None:
                self.taker_fills += 1
                return [fill]
            return []

        # LIMIT that doesn't cross → resting maker
        self._register_resting(order, book, flags)
        return []

    async def on_event(self, event: MarketEvent, book: OrderBook) -> list[Fill]:
        if event.market_id is None or event.asset_id is None:
            return []
        if event.event_type not in (EventType.TRADE_PRINT, EventType.BOOK_DELTA, EventType.BOOK_SNAPSHOT):
            return []

        fills: list[Fill] = []
        # Iterate over a copy because we mutate the dict on completion / miss
        for order_id, resting in list(self._resting.items()):
            if resting.order.market_id != event.market_id:
                continue
            if resting.order.asset_id != event.asset_id:
                continue

            # Trade-driven fill
            if event.event_type == EventType.TRADE_PRINT:
                fill = resting.process_trade_event(event, book)
                if fill is not None:
                    fills.append(fill)
                    if resting.is_done:
                        del self._resting[order_id]
                        self.maker_fills += 1
                continue

            # Book-driven walk-away check
            if resting.check_walk_away(book):
                miss = resting.to_missed_fill(event.ts or datetime.now(tz=UTC))
                fills.append(miss)
                del self._resting[order_id]
                self.missed_fills += 1

        return fills

    async def cancel(self, order_id: Any) -> None:
        self._resting.pop(order_id, None)

    # -----------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------

    def _preflight(self, order: Order, book: OrderBook) -> RealismFlag:
        flag = RealismFlag.CLEAN

        # Spread check
        spread = book.spread()
        if spread is not None and spread > THIN_MARKET_SPREAD:
            self.thin_market_flags += 1
            flag = RealismFlag.THIN_MARKET

        # Size-vs-depth check.
        # Audit P1-1: previously used depth_at_or_better (maker-perspective on
        # the SAME side as the order) which under-flagged would-move-market on
        # taker fills. The right metric is the OPPOSING-side liquidity that
        # this order would actually consume.
        if order.price is not None:
            depth = book.taker_consumable_depth(order.side, order.price)
            if depth > 0 and order.size > depth * WOULD_MOVE_MARKET_PCT:
                self.would_have_moved_market += 1
                flag = RealismFlag.WOULD_HAVE_MOVED_MARKET
        else:
            # MARKET order: use the entire visible opposite side at any price.
            opposite_levels = book.asks if order.side == Side.BUY else book.bids
            depth = sum((lvl.size for lvl in opposite_levels), start=Decimal(0))
            if depth > 0 and order.size > depth * WOULD_MOVE_MARKET_PCT:
                self.would_have_moved_market += 1
                flag = RealismFlag.WOULD_HAVE_MOVED_MARKET

        return flag

    def _crosses_book(self, order: Order, book: OrderBook) -> bool:
        if order.price is None:
            return True  # treat as market
        if order.side == Side.BUY:
            ask = book.best_ask()
            return ask is not None and order.price >= ask.price
        bid = book.best_bid()
        return bid is not None and order.price <= bid.price

    def _fill_taker(
        self,
        order: Order,
        book: OrderBook,
        flag: RealismFlag,
    ) -> Fill | None:
        """Walk the ladder, return single weighted-avg fill (no partials in V1)."""
        levels = book.asks if order.side == Side.BUY else book.bids
        if not levels:
            return None

        remaining = order.size
        consumed: list[tuple[Decimal, Decimal]] = []  # (price, size)
        for lvl in levels:
            if remaining <= 0:
                break
            # For LIMIT crosses, stop walking past our limit price
            if order.order_type == OrderType.LIMIT and order.price is not None:
                if order.side == Side.BUY and lvl.price > order.price:
                    break
                if order.side == Side.SELL and lvl.price < order.price:
                    break
            take = min(remaining, lvl.size)
            consumed.append((lvl.price, take))
            remaining -= take

        if not consumed:
            return None

        total_size = sum(s for _, s in consumed)
        if total_size <= 0:
            return None
        wavg_price = sum(p * s for p, s in consumed) / total_size
        wavg_price = Decimal(wavg_price).quantize(Decimal("0.000001"))

        # Slippage_bps vs the book MID at signal time. This is the honest
        # measure of "what the walk cost us" — replaces the old literature-
        # based realism haircut. For a buy: positive bps = we paid above mid
        # (adverse); for a sell: positive bps = we sold below mid (also
        # adverse). The sign is always "cost to us" so it sorts intuitively.
        mid = book.mid()
        slippage_bps: Decimal | None = None
        if mid is not None and mid > 0:
            if order.side == Side.BUY:
                raw = (wavg_price - mid) / mid
            else:
                raw = (mid - wavg_price) / mid
            slippage_bps = (raw * Decimal("10000")).quantize(Decimal("0.01"))

        return Fill(
            fill_id=uuid4(),
            order_id=order.order_id,
            sleeve_id=order.sleeve_id,
            market_id=order.market_id,
            asset_id=order.asset_id,
            side=order.side,
            price=wavg_price,
            size=total_size,
            fill_type=FillType.TAKER,
            ts_filled=order.ts_placed,
            realism_flag=flag,
            gas_cost=self.gas_cost,
            slippage_bps=slippage_bps,
            metadata={
                "levels_walked": len(consumed),
                "best_level_price": str(consumed[0][0]),
                "worst_level_price": str(consumed[-1][0]),
            },
        )

    def _register_resting(
        self,
        order: Order,
        book: OrderBook,
        flag: RealismFlag,
    ) -> None:
        if order.price is None:
            logger.warning("LIMIT without price ignored (order=%s)", order.order_id)
            return

        q_ahead = book.depth_at_or_better(order.side, order.price)
        # Approximate "queue behind 50% of depth" — the conservative half.
        q_ahead = q_ahead  # full depth as queue ahead
        last_depth_at_price = Decimal(0)
        # Actual size at exactly our price level (for cancel detection in future)
        levels = book.bids if order.side == Side.BUY else book.asks
        for lvl in levels:
            if lvl.price == order.price:
                last_depth_at_price = lvl.size
                break

        resting = RestingMaker(
            order=order,
            placed_at=order.ts_placed,
            placed_book_mid=book.mid(),
            q_ahead=q_ahead,
            realism_flag=flag,
            last_seen_depth_at_price=last_depth_at_price,
            cancel_decay=self.cancel_decay,
        )
        self._resting[order.order_id] = resting

    # -----------------------------------------------------------------------
    # Introspection
    # -----------------------------------------------------------------------

    def open_resting_count(self) -> int:
        return len(self._resting)

    def open_resting_for(self, sleeve_id: str) -> Iterable[RestingMaker]:
        return [r for r in self._resting.values() if r.order.sleeve_id == sleeve_id]


def plugin() -> EventReplayFillSimulator:
    return EventReplayFillSimulator()
