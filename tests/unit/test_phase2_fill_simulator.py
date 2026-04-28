"""Unit tests for EventReplayFillSimulator preflight + crossing logic."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from src.core.events import (
    EventType,
    MarketEvent,
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
        last_update_ts=datetime.now(tz=timezone.utc),
    )


def _order(side, otype, price, size):
    now = datetime.now(tz=timezone.utc)
    return Order(
        order_id=uuid4(),
        signal_id=uuid4(),
        sleeve_id="s",
        market_id="m",
        asset_id="a",
        side=side,
        order_type=otype,
        price=Decimal(price) if price is not None else None,
        size=Decimal(size),
        ts_signal=now,
        ts_placed=now,
    )


@pytest.mark.asyncio
async def test_market_buy_walks_ask_ladder():
    sim = EventReplayFillSimulator()
    book = _book(bids=[("0.49", "100")], asks=[("0.50", "20"), ("0.51", "50"), ("0.52", "100")])
    fills = await sim.submit(_order(Side.BUY, OrderType.MARKET, None, "70"), book)
    assert len(fills) == 1
    f = fills[0]
    # 20 @ 0.50 + 50 @ 0.51 = wavg ~0.5071
    assert Decimal("0.5070") <= f.price <= Decimal("0.5072")
    assert f.size == Decimal("70")
    assert sim.taker_fills == 1


@pytest.mark.asyncio
async def test_limit_does_not_cross_rests():
    sim = EventReplayFillSimulator()
    book = _book(bids=[("0.49", "100")], asks=[("0.51", "50")])
    fills = await sim.submit(_order(Side.BUY, OrderType.LIMIT, "0.49", "10"), book)
    assert fills == []
    assert sim.open_resting_count() == 1


@pytest.mark.asyncio
async def test_limit_crosses_book_acts_as_taker():
    sim = EventReplayFillSimulator()
    book = _book(bids=[("0.49", "100")], asks=[("0.51", "50")])
    # Buy LIMIT at 0.52 — crosses the 0.51 ask
    fills = await sim.submit(_order(Side.BUY, OrderType.LIMIT, "0.52", "10"), book)
    assert len(fills) == 1
    assert fills[0].price == Decimal("0.51")
    assert fills[0].fill_type.value == "taker"


@pytest.mark.asyncio
async def test_limit_crosses_walk_capped_at_limit_price():
    sim = EventReplayFillSimulator()
    book = _book(bids=[("0.49", "100")], asks=[("0.50", "10"), ("0.55", "100")])
    # Buy LIMIT at 0.51 — only 10 fillable at 0.50 (next level is 0.55, beyond limit)
    fills = await sim.submit(_order(Side.BUY, OrderType.LIMIT, "0.51", "50"), book)
    assert len(fills) == 1
    assert fills[0].size == Decimal("10")
    assert fills[0].price == Decimal("0.50")


@pytest.mark.asyncio
async def test_no_book_returns_empty():
    sim = EventReplayFillSimulator()
    book = _book(bids=[], asks=[])
    fills = await sim.submit(_order(Side.BUY, OrderType.MARKET, None, "10"), book)
    assert fills == []


@pytest.mark.asyncio
async def test_cancel_removes_resting():
    sim = EventReplayFillSimulator()
    book = _book(bids=[("0.49", "100")], asks=[("0.51", "50")])
    o = _order(Side.BUY, OrderType.LIMIT, "0.49", "10")
    await sim.submit(o, book)
    assert sim.open_resting_count() == 1
    await sim.cancel(o.order_id)
    assert sim.open_resting_count() == 0
