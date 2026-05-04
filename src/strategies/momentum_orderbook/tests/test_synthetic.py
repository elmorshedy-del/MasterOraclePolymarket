"""Synthetic-event tests for momentum_orderbook."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.core.events import EventType, MarketEvent, Side
from src.strategies.momentum_orderbook.strategy import MomentumOrderbook


def _snap(market_id: str, asset_id: str, bids: list[tuple[str, str]],
          asks: list[tuple[str, str]], ts: datetime | None = None) -> MarketEvent:
    return MarketEvent(
        event_id=__import__("uuid").uuid4(),
        event_type=EventType.BOOK_SNAPSHOT,
        venue="polymarket",
        market_id=market_id,
        asset_id=asset_id,
        ts=ts or datetime.now(tz=timezone.utc),
        payload={
            "asks": [{"price": p, "size": s} for p, s in asks],
            "bids": [{"price": p, "size": s} for p, s in bids],
        },
    )


@pytest.mark.asyncio
async def test_bullish_imbalance_buys_same_asset():
    strat = MomentumOrderbook()
    state: dict = {}
    # bid_size 800, ask_size 200 → imbalance 0.80 (bullish)
    sigs = await strat.on_event(
        _snap("m1", "a", bids=[("0.49", "800")], asks=[("0.51", "200")]), state)
    assert len(sigs) == 1
    assert sigs[0].asset_id == "a"
    assert sigs[0].side == Side.BUY
    assert sigs[0].metadata["direction"] == "bullish"


@pytest.mark.asyncio
async def test_bearish_imbalance_buys_paired_asset():
    strat = MomentumOrderbook()
    state: dict = {}
    # First, register a paired asset 'b'
    await strat.on_event(_snap("m1", "b", bids=[("0.49", "100")], asks=[("0.51", "100")]), state)
    # Now bearish on 'a': bid 200, ask 800 → imbalance 0.20
    sigs = await strat.on_event(
        _snap("m1", "a", bids=[("0.49", "200")], asks=[("0.51", "800")]), state)
    assert len(sigs) == 1
    # Bearish on 'a' → BUY paired 'b'
    assert sigs[0].asset_id == "b"
    assert sigs[0].metadata["direction"] == "bearish"


@pytest.mark.asyncio
async def test_balanced_book_does_not_fire():
    strat = MomentumOrderbook()
    state: dict = {}
    sigs = await strat.on_event(
        _snap("m1", "a", bids=[("0.49", "500")], asks=[("0.51", "500")]), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_thin_tob_depth_does_not_fire():
    strat = MomentumOrderbook(min_tob_depth_usd=Decimal("1000"))
    state: dict = {}
    # Total depth 1+4 = 5 contracts at mid 0.50 = $2.50 — way below $1000
    sigs = await strat.on_event(
        _snap("m1", "a", bids=[("0.49", "1")], asks=[("0.51", "4")]), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_outside_price_band_does_not_fire():
    strat = MomentumOrderbook(min_price=Decimal("0.20"), max_price=Decimal("0.80"))
    state: dict = {}
    # Price too high (mid 0.96)
    sigs = await strat.on_event(
        _snap("m1", "a", bids=[("0.95", "800")], asks=[("0.97", "200")]), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_bearish_without_paired_asset_does_not_fire():
    strat = MomentumOrderbook()
    state: dict = {}
    # Only one asset observed
    sigs = await strat.on_event(
        _snap("m1", "a", bids=[("0.49", "200")], asks=[("0.51", "800")]), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_cooldown_blocks_repeat():
    strat = MomentumOrderbook(cooldown_secs=300)
    state: dict = {}
    base = datetime(2026, 4, 30, 12, tzinfo=timezone.utc)
    sigs1 = await strat.on_event(
        _snap("m1", "a", bids=[("0.49", "800")], asks=[("0.51", "200")], ts=base), state)
    assert len(sigs1) == 1

    sigs2 = await strat.on_event(
        _snap("m1", "a", bids=[("0.49", "900")], asks=[("0.51", "100")],
              ts=base + timedelta(seconds=60)),
        state,
    )
    assert sigs2 == []

    sigs3 = await strat.on_event(
        _snap("m1", "a", bids=[("0.49", "900")], asks=[("0.51", "100")],
              ts=base + timedelta(seconds=400)),
        state,
    )
    assert len(sigs3) == 1


@pytest.mark.asyncio
async def test_size_inversely_proportional_to_ask():
    strat = MomentumOrderbook(target_notional_usd=Decimal("40"))
    state: dict = {}
    sigs = await strat.on_event(
        _snap("m1", "a", bids=[("0.49", "800")], asks=[("0.50", "200")]), state)
    # ask 0.50, size = 40/0.50 = 80
    assert sigs[0].size == Decimal("80.00")
