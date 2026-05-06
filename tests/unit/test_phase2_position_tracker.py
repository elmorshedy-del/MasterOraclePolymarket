"""Unit tests for PositionTracker — opening, closing, partial closes, P&L math."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from src.core.events import (
    Fill,
    FillType,
    RealismFlag,
    Side,
)
from src.execution.position_tracker import PositionTracker


def _fill(side, price, size, sleeve="s", market="m", asset="a", ftype=FillType.TAKER):
    return Fill(
        fill_id=uuid4(),
        order_id=uuid4(),
        sleeve_id=sleeve,
        market_id=market,
        asset_id=asset,
        side=side,
        price=Decimal(price),
        size=Decimal(size),
        fill_type=ftype,
        ts_filled=datetime.now(tz=UTC),
        realism_flag=RealismFlag.CLEAN,
        gas_cost=Decimal("0.10"),
    )


def test_open_position_no_trade():
    pt = PositionTracker()
    pt.register_sleeve("s", Decimal("5000"), edge_class="directional")
    trade = pt.on_fill(_fill(Side.BUY, "0.50", "100"), "strat", "default", "h")
    assert trade is None
    positions = pt.positions("s")
    assert len(positions) == 1
    assert positions[0].avg_entry == Decimal("0.50")
    assert positions[0].size == Decimal("100")


def test_close_full_position_emits_trade():
    pt = PositionTracker()
    pt.register_sleeve("s", Decimal("5000"), edge_class="directional")
    pt.on_fill(_fill(Side.BUY, "0.50", "100"), "strat", "default", "h")
    trade = pt.on_fill(_fill(Side.SELL, "0.55", "100"), "strat", "default", "h")
    assert trade is not None
    assert trade.entry_price == Decimal("0.50")
    assert trade.exit_price == Decimal("0.55")
    assert trade.entry_size == Decimal("100")
    assert trade.pnl > 0
    # No more open positions
    assert pt.positions("s") == []
    assert pt.trades_emitted == 1


def test_partial_close_keeps_remainder():
    pt = PositionTracker()
    pt.register_sleeve("s", Decimal("5000"), edge_class="directional")
    pt.on_fill(_fill(Side.BUY, "0.50", "100"), "strat", "default", "h")
    trade = pt.on_fill(_fill(Side.SELL, "0.55", "30"), "strat", "default", "h")
    assert trade is not None
    assert trade.entry_size == Decimal("30")
    # Remaining 70 still open
    positions = pt.positions("s")
    assert len(positions) == 1
    assert positions[0].size == Decimal("70")


def test_haircut_applied_per_edge_class():
    pt = PositionTracker(edge_class_by_sleeve={"s": "pure_arb"})
    pt.register_sleeve("s", Decimal("5000"), edge_class="pure_arb")
    pt.on_fill(_fill(Side.BUY, "0.50", "100"), "strat", "default", "h")
    trade = pt.on_fill(_fill(Side.SELL, "0.55", "100"), "strat", "default", "h")
    assert trade is not None
    # pure_arb override = -18%
    expected = trade.pnl * (Decimal("1") - Decimal("0.18"))
    assert abs(trade.pnl_after_haircut - expected) < Decimal("0.01")


def test_realized_pnl_accumulates():
    pt = PositionTracker()
    pt.register_sleeve("s", Decimal("5000"), edge_class="directional")
    pt.on_fill(_fill(Side.BUY, "0.50", "100"), "strat", "default", "h")
    pt.on_fill(_fill(Side.SELL, "0.55", "100"), "strat", "default", "h")
    pt.on_fill(_fill(Side.BUY, "0.60", "50"), "strat", "default", "h")
    pt.on_fill(_fill(Side.SELL, "0.62", "50"), "strat", "default", "h")
    pnl = pt.pnl("s")
    assert pnl.realized > 0
    assert pnl.open_position_count == 0


def test_missed_fill_does_not_create_position():
    pt = PositionTracker()
    pt.register_sleeve("s", Decimal("5000"), edge_class="directional")
    miss = _fill(Side.BUY, "0.50", "0", ftype=FillType.MISSED)
    trade = pt.on_fill(miss, "strat", "default", "h")
    assert trade is None
    assert pt.positions("s") == []
