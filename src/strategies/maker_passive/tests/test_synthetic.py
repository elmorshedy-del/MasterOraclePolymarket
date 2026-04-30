"""Synthetic-event tests for maker_passive."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.core.events import EventType, MarketEvent, Side
from src.strategies.maker_passive.strategy import MakerPassive


def _meta(market_id: str, asset_id: str, vol_24h: float, tick: str = "0.01") -> MarketEvent:
    return MarketEvent.make(
        event_type=EventType.MARKET_META,
        venue="polymarket",
        payload={
            "title": "test",
            "category": "politics",
            "asset_ids": [asset_id],
            "tick_size": tick,
            "tags_extra": {"volume_24h": vol_24h},
        },
        market_id=market_id,
        asset_id=asset_id,
    )


def _snap(market_id: str, asset_id: str, bid: str, ask: str,
          ts: datetime | None = None) -> MarketEvent:
    return MarketEvent(
        event_id=__import__("uuid").uuid4(),
        event_type=EventType.BOOK_SNAPSHOT,
        venue="polymarket",
        market_id=market_id,
        asset_id=asset_id,
        ts=ts or datetime.now(tz=timezone.utc),
        payload={
            "asks": [{"price": ask, "size": "100"}],
            "bids": [{"price": bid, "size": "100"}],
        },
    )


@pytest.mark.asyncio
async def test_fires_two_signals_when_thick():
    strat = MakerPassive(min_24h_volume_usd=1000)
    state: dict = {}
    await strat.on_event(_meta("m1", "a", vol_24h=10000), state)
    sigs = await strat.on_event(_snap("m1", "a", "0.48", "0.52"), state)
    assert len(sigs) == 2
    by_side = {s.side: s for s in sigs}
    # Buy at bid + tick, sell at ask - tick
    assert by_side[Side.BUY].price == Decimal("0.4900")
    assert by_side[Side.SELL].price == Decimal("0.5100")


@pytest.mark.asyncio
async def test_below_volume_filter_does_not_fire():
    strat = MakerPassive(min_24h_volume_usd=10000)
    state: dict = {}
    await strat.on_event(_meta("m1", "a", vol_24h=500), state)
    sigs = await strat.on_event(_snap("m1", "a", "0.48", "0.52"), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_narrow_spread_does_not_fire():
    strat = MakerPassive(min_24h_volume_usd=1000, min_spread_ticks=2)
    state: dict = {}
    await strat.on_event(_meta("m1", "a", vol_24h=10000), state)
    # spread = 1 tick
    sigs = await strat.on_event(_snap("m1", "a", "0.50", "0.51"), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_cooldown_blocks_re_emission():
    strat = MakerPassive(min_24h_volume_usd=1000, place_interval_secs=60)
    state: dict = {}
    base = datetime(2026, 4, 29, 12, tzinfo=timezone.utc)
    await strat.on_event(_meta("m1", "a", vol_24h=10000), state)
    sigs1 = await strat.on_event(_snap("m1", "a", "0.48", "0.52", ts=base), state)
    assert len(sigs1) == 2

    # 30s later — still within 60s cooldown
    sigs2 = await strat.on_event(_snap("m1", "a", "0.48", "0.52", ts=base + timedelta(seconds=30)), state)
    assert sigs2 == []

    # 90s later — past cooldown
    sigs3 = await strat.on_event(_snap("m1", "a", "0.48", "0.52", ts=base + timedelta(seconds=90)), state)
    assert len(sigs3) == 2


@pytest.mark.asyncio
async def test_no_meta_means_no_fire():
    strat = MakerPassive()
    state: dict = {}
    sigs = await strat.on_event(_snap("m1", "a", "0.48", "0.52"), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_concurrent_cap():
    strat = MakerPassive(min_24h_volume_usd=1000, max_concurrent_positions=2)
    state: dict = {}
    await strat.on_event(_meta("m1", "a", vol_24h=10000), state)
    sigs1 = await strat.on_event(_snap("m1", "a", "0.48", "0.52"), state)
    assert len(sigs1) == 2

    # New market → cap hit (already 2 active orders)
    await strat.on_event(_meta("m2", "b", vol_24h=10000), state)
    sigs2 = await strat.on_event(_snap("m2", "b", "0.48", "0.52"), state)
    assert sigs2 == []


@pytest.mark.asyncio
async def test_size_inversely_proportional_to_mid():
    strat = MakerPassive(min_24h_volume_usd=1000, target_notional_usd=Decimal("50"))
    state: dict = {}
    await strat.on_event(_meta("m1", "a", vol_24h=10000), state)
    sigs = await strat.on_event(_snap("m1", "a", "0.48", "0.52"), state)
    # mid = 0.50, size = 50/0.50 = 100
    assert sigs[0].size == Decimal("100.00")
    assert sigs[1].size == Decimal("100.00")


@pytest.mark.asyncio
async def test_uses_market_meta_tick_size():
    """Tick size from MARKET_META overrides strategy default."""
    strat = MakerPassive(min_24h_volume_usd=1000, tick_size=Decimal("0.01"))
    state: dict = {}
    # Meta says 0.001 tick — the smaller tick should be used
    await strat.on_event(_meta("m1", "a", vol_24h=10000, tick="0.001"), state)
    sigs = await strat.on_event(_snap("m1", "a", "0.480", "0.485"), state)
    assert len(sigs) == 2
    # spread 5 ticks @ 0.001 — passes min_spread_ticks=2
    by_side = {s.side: s for s in sigs}
    assert by_side[Side.BUY].price == Decimal("0.4810")    # 0.480 + 0.001
    assert by_side[Side.SELL].price == Decimal("0.4840")   # 0.485 - 0.001
