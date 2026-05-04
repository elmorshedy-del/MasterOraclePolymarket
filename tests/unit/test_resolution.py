"""Resolution pipeline + active-set clearing tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from src.core.events import (
    Fill,
    FillType,
    RealismFlag,
    Side,
)
from src.execution.position_tracker import PositionTracker
from src.strategies._lib.active_state import (
    ACTIVE_STATE_KEYS,
    clear_for_market,
)


def _fill(side, price, size, sleeve="s", market="m", asset="a"):
    return Fill(
        fill_id=uuid4(),
        order_id=uuid4(),
        sleeve_id=sleeve,
        market_id=market,
        asset_id=asset,
        side=side,
        price=Decimal(price),
        size=Decimal(size),
        fill_type=FillType.TAKER,
        ts_filled=datetime.now(tz=timezone.utc),
        realism_flag=RealismFlag.CLEAN,
        gas_cost=Decimal("0.10"),
    )


def test_redeem_market_winner_pays_one_dollar():
    pt = PositionTracker()
    pt.register_sleeve("s", Decimal("5000"), edge_class="pure_arb")
    # Open: bought asset 'a' at 0.40 size 100
    pt.on_fill(_fill(Side.BUY, "0.40", "100"), "strat", "default", "h")

    trades = pt.redeem_market(
        market_id="m",
        winning_asset_id="a",
        ts=datetime.now(tz=timezone.utc),
    )
    assert len(trades) == 1
    t = trades[0]
    # exit at $1.00, entry 0.40, size 100 → raw 60, minus gas
    assert t.exit_price == Decimal("1")
    assert t.pnl > Decimal("59")        # gas eats a tiny bit
    assert t.tags["settlement"] is True
    # Position is gone
    assert pt.positions("s") == []


def test_redeem_market_loser_zero_payout():
    pt = PositionTracker()
    pt.register_sleeve("s", Decimal("5000"))
    pt.on_fill(_fill(Side.BUY, "0.60", "100", asset="losing_token"), "strat", "default", "h")

    trades = pt.redeem_market(
        market_id="m",
        winning_asset_id="winning_token",      # different from our holding
        ts=datetime.now(tz=timezone.utc),
    )
    assert len(trades) == 1
    assert trades[0].exit_price == Decimal("0")
    assert trades[0].pnl < Decimal("-59")  # lost full entry value + gas
    assert pt.positions("s") == []


def test_redeem_market_unknown_winner_closes_at_avg_entry():
    pt = PositionTracker()
    pt.register_sleeve("s", Decimal("5000"))
    pt.on_fill(_fill(Side.BUY, "0.55", "100"), "strat", "default", "h")

    trades = pt.redeem_market(
        market_id="m",
        winning_asset_id=None,
        ts=datetime.now(tz=timezone.utc),
    )
    assert len(trades) == 1
    # Closing at avg_entry → raw pnl = 0, minus gas
    assert trades[0].exit_price == Decimal("0.55")
    assert trades[0].pnl < Decimal("0")        # only gas
    assert trades[0].pnl > Decimal("-1")       # but trivial


def test_redeem_market_no_open_positions_is_noop():
    pt = PositionTracker()
    trades = pt.redeem_market(
        market_id="m",
        winning_asset_id="a",
        ts=datetime.now(tz=timezone.utc),
    )
    assert trades == []


def test_clear_for_market_removes_market_id_entries():
    state: dict = {
        "active_arbs": {"m1", "m2", "m3"},
        "_active_snipes": {("m1", "yes"), ("m2", "no"), ("m3", "yes")},
        "_active_orders": {("m1", "yes", "buy"), ("m2", "no", "sell")},
    }
    removed = clear_for_market(state, "m1")
    assert removed == 3
    assert "m1" not in state["active_arbs"]
    assert ("m1", "yes") not in state["_active_snipes"]
    assert ("m1", "yes", "buy") not in state["_active_orders"]
    # Other markets untouched
    assert "m2" in state["active_arbs"]
    assert ("m2", "no") in state["_active_snipes"]


def test_clear_for_market_handles_missing_keys():
    """No exception when state lacks any of the conventional keys."""
    state: dict = {}
    assert clear_for_market(state, "m1") == 0


def test_active_state_keys_cover_shipped_strategies():
    """Every strategy that uses an active-set must appear in ACTIVE_STATE_KEYS."""
    expected = {
        "active_arbs",      # cross_outcome_arb, basket_arb
        "_active_snipes",   # redemption_sniper
        "_active_tails",    # weather_tail_sell
        "_active_buys",     # weather_tail_buy
        "_active_fades",    # mean_revert_post_spike
        "_active_mom",      # momentum_orderbook
        "_active_orders",   # maker_passive
    }
    assert expected.issubset(set(ACTIVE_STATE_KEYS)), (
        f"shipped strategies use active-state keys {expected - set(ACTIVE_STATE_KEYS)} "
        "that are missing from ACTIVE_STATE_KEYS — they would never get cleared "
        "on MARKET_RESOLVED, leaving the strategy frozen on those markets"
    )
