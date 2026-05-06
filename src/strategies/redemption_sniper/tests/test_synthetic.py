"""Synthetic-event tests for redemption_sniper."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.core.events import EventType, MarketEvent
from src.strategies.redemption_sniper.strategy import RedemptionSniper


def _meta(market_id: str, end: datetime, asset_ids: list[str]) -> MarketEvent:
    return MarketEvent.make(
        event_type=EventType.MARKET_META,
        venue="polymarket",
        payload={
            "title": "test",
            "category": "politics",
            "asset_ids": asset_ids,
            "end_time": end.isoformat(),
        },
        market_id=market_id,
        asset_id=asset_ids[0],
    )


def _snap(market_id: str, asset_id: str, ask: str,
          ts: datetime | None = None) -> MarketEvent:
    return MarketEvent(
        event_id=__import__("uuid").uuid4(),
        event_type=EventType.BOOK_SNAPSHOT,
        venue="polymarket",
        market_id=market_id,
        asset_id=asset_id,
        ts=ts or datetime.now(tz=UTC),
        payload={
            "asks": [{"price": ask, "size": "100"}],
            "bids": [{"price": "0.50", "size": "100"}],
        },
    )


def _trade(market_id: str, asset_id: str, price: str,
           ts: datetime | None = None) -> MarketEvent:
    return MarketEvent(
        event_id=__import__("uuid").uuid4(),
        event_type=EventType.TRADE_PRINT,
        venue="polymarket",
        market_id=market_id,
        asset_id=asset_id,
        ts=ts or datetime.now(tz=UTC),
        payload={"price": price, "size": "10", "side": "sell"},
    )


@pytest.mark.asyncio
async def test_fires_inside_window_and_price_band():
    strat = RedemptionSniper()
    state: dict = {}
    now = datetime(2026, 4, 29, 12, tzinfo=UTC)
    end = now + timedelta(minutes=30)  # within 1h window

    await strat.on_event(_meta("m1", end, ["yes"]), state)
    sigs = await strat.on_event(_snap("m1", "yes", "0.98", ts=now), state)
    assert len(sigs) == 1
    assert sigs[0].asset_id == "yes"
    # 25 bps = 0.0025 → 0.98 + 0.0025 = 0.9825
    assert sigs[0].price == Decimal("0.9825")


@pytest.mark.asyncio
async def test_outside_time_window_does_not_fire():
    strat = RedemptionSniper()
    state: dict = {}
    now = datetime(2026, 4, 29, 12, tzinfo=UTC)
    end = now + timedelta(hours=24)  # well outside 1h window

    await strat.on_event(_meta("m1", end, ["yes"]), state)
    sigs = await strat.on_event(_snap("m1", "yes", "0.98", ts=now), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_outside_price_band_does_not_fire():
    strat = RedemptionSniper()
    state: dict = {}
    now = datetime(2026, 4, 29, 12, tzinfo=UTC)
    end = now + timedelta(minutes=30)
    await strat.on_event(_meta("m1", end, ["yes"]), state)

    # ask too low
    sigs = await strat.on_event(_snap("m1", "yes", "0.85", ts=now), state)
    assert sigs == []
    # ask too high (past upper bound)
    sigs = await strat.on_event(_snap("m1", "yes", "0.999", ts=now), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_adverse_print_blocks_fire():
    strat = RedemptionSniper()
    state: dict = {}
    now = datetime(2026, 4, 29, 12, tzinfo=UTC)
    end = now + timedelta(minutes=30)

    await strat.on_event(_meta("m1", end, ["yes"]), state)
    # An adverse trade just happened (at 0.96, more than 1¢ below 0.98)
    await strat.on_event(_trade("m1", "yes", "0.96", ts=now - timedelta(seconds=10)), state)
    sigs = await strat.on_event(_snap("m1", "yes", "0.98", ts=now), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_adverse_print_outside_window_does_not_block():
    strat = RedemptionSniper(recent_window_secs=60)
    state: dict = {}
    now = datetime(2026, 4, 29, 12, tzinfo=UTC)
    end = now + timedelta(minutes=30)

    await strat.on_event(_meta("m1", end, ["yes"]), state)
    # Adverse trade was 5 minutes ago — outside 60s window
    await strat.on_event(_trade("m1", "yes", "0.96", ts=now - timedelta(minutes=5)), state)
    sigs = await strat.on_event(_snap("m1", "yes", "0.98", ts=now), state)
    assert len(sigs) == 1


@pytest.mark.asyncio
async def test_no_meta_means_no_fire():
    strat = RedemptionSniper()
    state: dict = {}
    sigs = await strat.on_event(_snap("m1", "yes", "0.98"), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_does_not_re_snipe_same_asset():
    strat = RedemptionSniper()
    state: dict = {}
    now = datetime(2026, 4, 29, 12, tzinfo=UTC)
    end = now + timedelta(minutes=30)

    await strat.on_event(_meta("m1", end, ["yes"]), state)
    sigs1 = await strat.on_event(_snap("m1", "yes", "0.98", ts=now), state)
    assert len(sigs1) == 1
    sigs2 = await strat.on_event(_snap("m1", "yes", "0.98", ts=now + timedelta(seconds=5)), state)
    assert sigs2 == []
