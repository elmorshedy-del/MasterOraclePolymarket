"""Audit P1 fixes — preflight book-side, replay pagination math.

Med-2 (mode-history reset) is a SQL-level fix tested via the actual upsert
when a DB is wired in; the SQL is reviewed in code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from src.core.events import (
    Order,
    OrderBook,
    OrderType,
    PriceLevel,
    Side,
)
from src.execution.event_replay import EventReplayFillSimulator


def _book(bids, asks):
    return OrderBook(
        market_id="m", asset_id="a",
        bids=[PriceLevel(price=Decimal(p), size=Decimal(s)) for p, s in bids],
        asks=[PriceLevel(price=Decimal(p), size=Decimal(s)) for p, s in asks],
        last_update_ts=datetime.now(tz=UTC),
    )


def test_taker_consumable_depth_uses_opposing_side():
    book = _book(
        bids=[("0.49", "1000")],
        asks=[("0.50", "10"), ("0.51", "20"), ("0.55", "200")],
    )
    # BUY @ 0.51 → consumable = asks at <=0.51 = 30
    assert book.taker_consumable_depth(Side.BUY, Decimal("0.51")) == Decimal("30")
    # SELL @ 0.49 → consumable = bids at >=0.49 = 1000
    assert book.taker_consumable_depth(Side.SELL, Decimal("0.49")) == Decimal("1000")


def test_depth_at_or_better_remains_maker_perspective():
    """Confirm the maker-side method is unchanged for queue math."""
    book = _book(
        bids=[("0.50", "100"), ("0.49", "200")],
        asks=[("0.51", "50")],
    )
    assert book.depth_at_or_better(Side.BUY, Decimal("0.50")) == Decimal("100")
    assert book.depth_at_or_better(Side.SELL, Decimal("0.51")) == Decimal("50")


@pytest.mark.asyncio
async def test_preflight_flags_buy_taker_eating_thin_asks():
    """A BUY taker eating most of the ask side flags would-have-moved-market.
    Pre-fix the check used same-side bid depth and missed this case."""
    sim = EventReplayFillSimulator()
    book = _book(
        bids=[("0.49", "1000")],          # huge bid wall (would have masked the bug)
        asks=[("0.50", "10")],            # only 10 to consume
    )
    order = Order(
        order_id=uuid4(), signal_id=uuid4(), sleeve_id="s",
        market_id="m", asset_id="a",
        side=Side.BUY, order_type=OrderType.LIMIT,
        price=Decimal("0.50"), size=Decimal("9"),     # 90% of ask depth
        ts_signal=datetime.now(tz=UTC),
        ts_placed=datetime.now(tz=UTC),
    )
    fills = await sim.submit(order, book)
    assert len(fills) == 1
    assert fills[0].realism_flag.value == "would_have_moved_market"
    assert sim.would_have_moved_market == 1


@pytest.mark.asyncio
async def test_preflight_does_not_flag_when_well_within_ask_depth():
    sim = EventReplayFillSimulator()
    book = _book(
        bids=[("0.49", "100")],
        asks=[("0.50", "10000")],         # huge ask wall
    )
    order = Order(
        order_id=uuid4(), signal_id=uuid4(), sleeve_id="s",
        market_id="m", asset_id="a",
        side=Side.BUY, order_type=OrderType.LIMIT,
        price=Decimal("0.50"), size=Decimal("100"),    # 1% of ask depth
        ts_signal=datetime.now(tz=UTC),
        ts_placed=datetime.now(tz=UTC),
    )
    fills = await sim.submit(order, book)
    assert sim.would_have_moved_market == 0
    assert fills[0].realism_flag.value == "clean"


@pytest.mark.asyncio
async def test_preflight_flags_market_order_eating_book():
    sim = EventReplayFillSimulator()
    book = _book(
        bids=[("0.49", "1000")],
        asks=[("0.50", "10"), ("0.51", "10")],   # 20 total ask depth
    )
    order = Order(
        order_id=uuid4(), signal_id=uuid4(), sleeve_id="s",
        market_id="m", asset_id="a",
        side=Side.BUY, order_type=OrderType.MARKET,
        price=None, size=Decimal("15"),
        ts_signal=datetime.now(tz=UTC),
        ts_placed=datetime.now(tz=UTC),
    )
    await sim.submit(order, book)
    assert sim.would_have_moved_market == 1
