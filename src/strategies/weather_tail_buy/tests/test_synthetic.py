"""Synthetic-event tests for weather_tail_buy."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.core.events import EventType, MarketEvent
from src.strategies.weather_tail_buy.strategy import WeatherTailBuy


def _meta(market_id: str, asset_id: str, category: str) -> MarketEvent:
    return MarketEvent.make(
        event_type=EventType.MARKET_META,
        venue="polymarket",
        payload={"title": "test", "category": category, "asset_ids": [asset_id]},
        market_id=market_id,
        asset_id=asset_id,
    )


def _snap(market_id: str, asset_id: str, ask: str) -> MarketEvent:
    return MarketEvent.make(
        event_type=EventType.BOOK_SNAPSHOT,
        venue="polymarket",
        payload={"asks": [{"price": ask, "size": "100"}],
                 "bids": [{"price": "0.01", "size": "100"}]},
        market_id=market_id,
        asset_id=asset_id,
    )


@pytest.mark.asyncio
async def test_fires_on_weather_in_band():
    strat = WeatherTailBuy()
    state: dict = {}
    await strat.on_event(_meta("m1", "tail", "weather/nyc/temp"), state)
    sigs = await strat.on_event(_snap("m1", "tail", "0.03"), state)
    assert len(sigs) == 1
    assert sigs[0].metadata["category"] == "weather/nyc/temp"


@pytest.mark.asyncio
async def test_above_band_does_not_fire():
    strat = WeatherTailBuy()
    state: dict = {}
    await strat.on_event(_meta("m1", "tail", "weather"), state)
    sigs = await strat.on_event(_snap("m1", "tail", "0.10"), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_non_weather_does_not_fire():
    strat = WeatherTailBuy()
    state: dict = {}
    await strat.on_event(_meta("m1", "tail", "politics"), state)
    sigs = await strat.on_event(_snap("m1", "tail", "0.03"), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_size_calculation():
    strat = WeatherTailBuy(target_notional_usd=Decimal("25"))
    state: dict = {}
    await strat.on_event(_meta("m1", "tail", "weather"), state)
    sigs = await strat.on_event(_snap("m1", "tail", "0.05"), state)
    # 25 / 0.05 = 500
    assert sigs[0].size == Decimal("500.00")


@pytest.mark.asyncio
async def test_does_not_re_fire():
    strat = WeatherTailBuy()
    state: dict = {}
    await strat.on_event(_meta("m1", "tail", "weather"), state)
    sigs1 = await strat.on_event(_snap("m1", "tail", "0.03"), state)
    assert len(sigs1) == 1
    sigs2 = await strat.on_event(_snap("m1", "tail", "0.03"), state)
    assert sigs2 == []
