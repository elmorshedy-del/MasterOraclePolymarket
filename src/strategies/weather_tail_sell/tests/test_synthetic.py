"""Synthetic-event tests for weather_tail_sell."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.core.events import EventType, MarketEvent
from src.strategies.weather_tail_sell.strategy import WeatherTailSell


def _meta(market_id: str, asset_id: str, category: str) -> MarketEvent:
    return MarketEvent.make(
        event_type=EventType.MARKET_META,
        venue="polymarket",
        payload={"title": "test", "category": category, "asset_ids": [asset_id]},
        market_id=market_id,
        asset_id=asset_id,
    )


def _snap(market_id: str, asset_id: str, ask: str, ts: datetime | None = None) -> MarketEvent:
    return MarketEvent(
        event_id=__import__("uuid").uuid4(),
        event_type=EventType.BOOK_SNAPSHOT,
        venue="polymarket",
        market_id=market_id,
        asset_id=asset_id,
        ts=ts or datetime.now(tz=UTC),
        payload={"asks": [{"price": ask, "size": "100"}],
                 "bids": [{"price": "0.30", "size": "100"}]},
    )


def _trade(market_id: str, asset_id: str, price: str, ts: datetime) -> MarketEvent:
    return MarketEvent(
        event_id=__import__("uuid").uuid4(),
        event_type=EventType.TRADE_PRINT,
        venue="polymarket",
        market_id=market_id,
        asset_id=asset_id,
        ts=ts,
        payload={"price": price, "size": "10", "side": "sell"},
    )


@pytest.mark.asyncio
async def test_fires_on_weather_in_band():
    strat = WeatherTailSell()
    state: dict = {}
    await strat.on_event(_meta("m1", "tail", "weather/nyc/temp"), state)
    sigs = await strat.on_event(_snap("m1", "tail", "0.96"), state)
    assert len(sigs) == 1
    assert sigs[0].metadata["category"] == "weather/nyc/temp"


@pytest.mark.asyncio
async def test_non_weather_category_does_not_fire():
    strat = WeatherTailSell()
    state: dict = {}
    await strat.on_event(_meta("m1", "tail", "politics"), state)
    sigs = await strat.on_event(_snap("m1", "tail", "0.96"), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_below_band_does_not_fire():
    strat = WeatherTailSell()
    state: dict = {}
    await strat.on_event(_meta("m1", "tail", "weather"), state)
    sigs = await strat.on_event(_snap("m1", "tail", "0.85"), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_adverse_print_blocks_fire():
    strat = WeatherTailSell()
    state: dict = {}
    now = datetime(2026, 4, 29, 12, tzinfo=UTC)
    await strat.on_event(_meta("m1", "tail", "weather"), state)
    await strat.on_event(_trade("m1", "tail", "0.92", ts=now - timedelta(seconds=60)), state)
    sigs = await strat.on_event(_snap("m1", "tail", "0.96", ts=now), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_no_meta_means_no_fire():
    strat = WeatherTailSell()
    state: dict = {}
    sigs = await strat.on_event(_snap("m1", "tail", "0.97"), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_does_not_re_fire_same_asset():
    strat = WeatherTailSell()
    state: dict = {}
    await strat.on_event(_meta("m1", "tail", "weather"), state)
    sigs1 = await strat.on_event(_snap("m1", "tail", "0.97"), state)
    assert len(sigs1) == 1
    sigs2 = await strat.on_event(_snap("m1", "tail", "0.97"), state)
    assert sigs2 == []


@pytest.mark.asyncio
async def test_size_inversely_proportional_to_price():
    strat = WeatherTailSell(target_notional_usd=Decimal("50"))
    state: dict = {}
    await strat.on_event(_meta("m1", "tail", "weather"), state)
    sigs = await strat.on_event(_snap("m1", "tail", "0.95"), state)
    assert sigs[0].size == Decimal("52.63")  # 50 / 0.95
