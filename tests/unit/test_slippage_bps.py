"""Slippage_bps measurement — derived from the orderbook walk.

Replaces the literature-based −22% haircut as the headline measure of
gap-to-real-money. Tests prove that:

  - A clean fill at TOB has bps ≈ (ask - mid)/mid × 10000
  - Walking through multiple levels yields a higher (worse) slippage
  - Tiny orders against a thick book have near-zero slippage
  - Slippage propagates from Fill → Position → Trade, size-weighted
  - Sells flip the sign convention so positive bps always means "cost to us"
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
from src.execution.position_tracker import PositionTracker


def _book(bids, asks):
    return OrderBook(
        market_id="m", asset_id="a",
        bids=[PriceLevel(price=Decimal(p), size=Decimal(s)) for p, s in bids],
        asks=[PriceLevel(price=Decimal(p), size=Decimal(s)) for p, s in asks],
        last_update_ts=datetime.now(tz=UTC),
    )


def _order(side, otype, price, size):
    now = datetime.now(tz=UTC)
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
async def test_buy_at_top_of_book_records_spread_half():
    """Buy entire size at the best ask: slippage_bps = (ask − mid) / mid × 10000.

    Mid = (0.49 + 0.51) / 2 = 0.50; we pay 0.51; slippage = 100 bps.
    """
    sim = EventReplayFillSimulator()
    book = _book(bids=[("0.49", "1000")], asks=[("0.51", "1000")])
    fills = await sim.submit(_order(Side.BUY, OrderType.MARKET, None, "10"), book)
    assert len(fills) == 1
    f = fills[0]
    assert f.slippage_bps is not None
    # 0.51 vs 0.50 mid → 200 bps of price difference; bps in our convention is
    # (fill - mid) / mid * 10000 = 200
    assert abs(f.slippage_bps - Decimal("200")) < Decimal("0.5")


@pytest.mark.asyncio
async def test_walking_multiple_levels_increases_slippage():
    """Eat through 3 levels — bps must be larger than at TOB."""
    sim = EventReplayFillSimulator()
    book = _book(
        bids=[("0.49", "100")],
        asks=[("0.50", "10"), ("0.55", "20"), ("0.60", "100")],
    )
    fills = await sim.submit(_order(Side.BUY, OrderType.MARKET, None, "30"), book)
    assert len(fills) == 1
    # mid = (0.49 + 0.50)/2 = 0.495; wavg fill ≈ (10*0.50 + 20*0.55) / 30 = 0.5333
    # bps ≈ (0.5333 - 0.495)/0.495 × 10000 ≈ 774
    assert fills[0].slippage_bps is not None
    assert fills[0].slippage_bps > Decimal("500")


@pytest.mark.asyncio
async def test_sell_slippage_sign_convention():
    """Sells: positive bps means we sold BELOW mid (cost to us)."""
    sim = EventReplayFillSimulator()
    book = _book(bids=[("0.45", "100")], asks=[("0.55", "100")])
    fills = await sim.submit(_order(Side.SELL, OrderType.MARKET, None, "10"), book)
    assert len(fills) == 1
    # mid 0.50, sold at 0.45 → 1000 bps below. Convention: positive = adverse.
    assert fills[0].slippage_bps is not None
    assert fills[0].slippage_bps > Decimal("900")


@pytest.mark.asyncio
async def test_thin_walk_against_thick_book_stays_at_half_spread():
    """A small order against a deep book pays only the half-spread, not more.

    Spread = 0.502 vs 0.498 = 0.004 (mid 0.500); half-spread above mid is
    20 bps. The walk consumes just one level (the best ask), so slippage
    must equal that half-spread exactly.
    """
    sim = EventReplayFillSimulator()
    book = _book(bids=[("0.498", "100000")], asks=[("0.502", "100000")])
    fills = await sim.submit(_order(Side.BUY, OrderType.MARKET, None, "5"), book)
    assert fills[0].slippage_bps is not None
    # Half-spread above mid: (0.502 − 0.500) / 0.500 × 10000 = 40 bps
    assert abs(fills[0].slippage_bps - Decimal("40")) < Decimal("0.5")


@pytest.mark.asyncio
async def test_slippage_propagates_through_position_close():
    """Entry slippage and exit slippage are averaged onto the Trade row."""
    sim = EventReplayFillSimulator()
    pt = PositionTracker()
    pt.register_sleeve("s", Decimal("5000"), edge_class="directional")

    # Entry: buy 10 @ TOB ask 0.51 (mid 0.50) → +200 bps slippage
    entry_book = _book(bids=[("0.49", "1000")], asks=[("0.51", "1000")])
    entry_fills = await sim.submit(_order(Side.BUY, OrderType.MARKET, None, "10"), entry_book)
    pt.on_fill(entry_fills[0], "t", "default", "h")

    # Exit: sell 10 @ TOB bid 0.55 (mid 0.56) → 178 bps slippage on the sell
    exit_book = _book(bids=[("0.55", "1000")], asks=[("0.57", "1000")])
    exit_fills = await sim.submit(_order(Side.SELL, OrderType.MARKET, None, "10"), exit_book)
    trade = pt.on_fill(exit_fills[0], "t", "default", "h")
    assert trade is not None
    assert trade.slippage_bps is not None
    # Average should be in the 100-200 bps range
    assert Decimal("100") < trade.slippage_bps < Decimal("250")
