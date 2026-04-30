"""Synthetic-event tests for basket_arb."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.core.events import EventType, MarketEvent, Side
from src.strategies.basket_arb.strategy import BasketArb


def _snap(market_id: str, asset_id: str, asks: list[tuple[str, str]]) -> MarketEvent:
    return MarketEvent.make(
        event_type=EventType.BOOK_SNAPSHOT,
        venue="polymarket",
        payload={
            "asks": [{"price": p, "size": s} for p, s in asks],
            "bids": [{"price": "0.30", "size": "100"}],
        },
        market_id=market_id,
        asset_id=asset_id,
    )


def _meta(market_id: str, asset_ids: list[str]) -> MarketEvent:
    return MarketEvent.make(
        event_type=EventType.MARKET_META,
        venue="polymarket",
        payload={
            "title": "test",
            "category": "politics",
            "asset_ids": asset_ids,
        },
        market_id=market_id,
        asset_id=asset_ids[0] if asset_ids else None,
    )


@pytest.mark.asyncio
async def test_three_leg_basket_below_threshold_fires_three_signals():
    strat = BasketArb()
    state: dict = {}

    await strat.on_event(_snap("m1", "a", [("0.30", "100")]), state)
    await strat.on_event(_snap("m1", "b", [("0.30", "100")]), state)
    sigs = await strat.on_event(_snap("m1", "c", [("0.30", "100")]), state)

    # sum = 0.90, edge = 1000 bps → fires
    assert len(sigs) == 3
    assert {s.side for s in sigs} == {Side.BUY}
    assert {s.asset_id for s in sigs} == {"a", "b", "c"}


@pytest.mark.asyncio
async def test_below_min_legs_does_not_fire():
    strat = BasketArb(min_legs=3)
    state: dict = {}

    await strat.on_event(_snap("m1", "a", [("0.30", "100")]), state)
    sigs = await strat.on_event(_snap("m1", "b", [("0.30", "100")]), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_meta_says_more_legs_than_observed_blocks_fire():
    """If MARKET_META reports 5 outcomes but we've only seen 3, do not fire."""
    strat = BasketArb(min_legs=3)
    state: dict = {}

    await strat.on_event(_meta("m1", ["a", "b", "c", "d", "e"]), state)
    await strat.on_event(_snap("m1", "a", [("0.20", "100")]), state)
    await strat.on_event(_snap("m1", "b", [("0.20", "100")]), state)
    sigs = await strat.on_event(_snap("m1", "c", [("0.20", "100")]), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_meta_legs_match_observed_allows_fire():
    strat = BasketArb(min_legs=3)
    state: dict = {}

    await strat.on_event(_meta("m1", ["a", "b", "c"]), state)
    await strat.on_event(_snap("m1", "a", [("0.20", "100")]), state)
    await strat.on_event(_snap("m1", "b", [("0.20", "100")]), state)
    sigs = await strat.on_event(_snap("m1", "c", [("0.20", "100")]), state)
    assert len(sigs) == 3


@pytest.mark.asyncio
async def test_sum_above_threshold_does_not_fire():
    strat = BasketArb()
    state: dict = {}
    await strat.on_event(_snap("m1", "a", [("0.50", "100")]), state)
    await strat.on_event(_snap("m1", "b", [("0.40", "100")]), state)
    sigs = await strat.on_event(_snap("m1", "c", [("0.20", "100")]), state)
    # sum 1.10 > 0.98 → no fire
    assert sigs == []


@pytest.mark.asyncio
async def test_does_not_re_arb_same_market():
    strat = BasketArb()
    state: dict = {}

    await strat.on_event(_snap("m1", "a", [("0.20", "100")]), state)
    await strat.on_event(_snap("m1", "b", [("0.20", "100")]), state)
    sigs1 = await strat.on_event(_snap("m1", "c", [("0.20", "100")]), state)
    assert len(sigs1) == 3

    sigs2 = await strat.on_event(_snap("m1", "c", [("0.20", "100")]), state)
    assert sigs2 == []


@pytest.mark.asyncio
async def test_concurrent_position_cap():
    strat = BasketArb(max_concurrent_positions=1)
    state: dict = {}

    for asset in ["a", "b", "c"]:
        await strat.on_event(_snap("m1", asset, [("0.20", "100")]), state)
    # First market fires
    sigs = await strat.on_event(_snap("m1", "c", [("0.20", "100")]), state)
    # already fired (state preserved); set m2 fresh and try
    state2: dict = {}
    state2["active_arbs"] = {"m1"}  # simulate cap reached
    state2.setdefault("_market_assets", {}).setdefault("m2", set()).update({"a2", "b2", "c2"})
    state2["_books"] = {
        "a2": {"asks": [(Decimal("0.20"), Decimal("100"))], "bids": [], "market_id": "m2"},
        "b2": {"asks": [(Decimal("0.20"), Decimal("100"))], "bids": [], "market_id": "m2"},
        "c2": {"asks": [(Decimal("0.20"), Decimal("100"))], "bids": [], "market_id": "m2"},
    }
    sigs = await strat.on_event(_snap("m2", "c2", [("0.20", "100")]), state2)
    assert sigs == []


@pytest.mark.asyncio
async def test_size_inversely_proportional_to_price():
    strat = BasketArb(max_size_per_leg_usd=Decimal("100"))
    state: dict = {}
    await strat.on_event(_snap("m1", "a", [("0.20", "100")]), state)
    await strat.on_event(_snap("m1", "b", [("0.30", "100")]), state)
    sigs = await strat.on_event(_snap("m1", "c", [("0.40", "100")]), state)
    by_asset = {s.asset_id: s for s in sigs}
    assert by_asset["a"].size == Decimal("500.00")    # 100 / 0.20
    assert by_asset["b"].size == Decimal("333.33")    # 100 / 0.30
    assert by_asset["c"].size == Decimal("250.00")    # 100 / 0.40


@pytest.mark.asyncio
async def test_no_ask_on_a_leg_blocks_fire():
    strat = BasketArb()
    state: dict = {}
    await strat.on_event(_snap("m1", "a", [("0.20", "100")]), state)
    await strat.on_event(_snap("m1", "b", [("0.20", "100")]), state)
    # Leg c has empty ask side
    await strat.on_event(_snap("m1", "c", []), state)
    # Should still not fire (asks list empty for c)
    sigs = await strat.on_event(_snap("m1", "c", []), state)
    assert sigs == []
