"""Synthetic-event tests for whale_copy_eod."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.core.events import EventType, MarketEvent, Side
from src.strategies.whale_copy_eod.strategy import WhaleCopyEod


def _activity(market_id: str, asset_id: str, *, wallet: str, side: str,
              size: str = "100", price: str = "0.50", usd_value: str = "1000",
              ts: datetime | None = None) -> MarketEvent:
    return MarketEvent(
        event_id=__import__("uuid").uuid4(),
        event_type=EventType.ACTIVITY_TRADE,
        venue="polymarket",
        market_id=market_id,
        asset_id=asset_id,
        ts=ts or datetime.now(tz=UTC),
        payload={
            "wallet": wallet,
            "side": side,
            "size": size,
            "price": price,
            "usd_value": usd_value,
        },
    )


def _snap(market_id: str, asset_id: str, ask: str = "0.50") -> MarketEvent:
    return MarketEvent.make(
        event_type=EventType.BOOK_SNAPSHOT,
        venue="polymarket",
        payload={"asks": [{"price": ask, "size": "100"}],
                 "bids": [{"price": "0.45", "size": "100"}]},
        market_id=market_id,
        asset_id=asset_id,
    )


@pytest.mark.asyncio
async def test_copies_tracked_wallet():
    strat = WhaleCopyEod(tracked_wallets={"sharp1"})
    state: dict = {}
    await strat.on_event(_snap("m1", "a"), state)
    sigs = await strat.on_event(_activity("m1", "a", wallet="sharp1", side="BUY"), state)
    assert len(sigs) == 1
    assert sigs[0].side == Side.BUY
    assert sigs[0].asset_id == "a"
    assert "sharp1" in sigs[0].metadata["wallet"]


@pytest.mark.asyncio
async def test_ignores_untracked_wallet():
    strat = WhaleCopyEod(tracked_wallets={"sharp1"})
    state: dict = {}
    await strat.on_event(_snap("m1", "a"), state)
    sigs = await strat.on_event(_activity("m1", "a", wallet="random_retail", side="BUY"), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_below_min_usd_value_does_not_copy():
    strat = WhaleCopyEod(tracked_wallets={"sharp1"}, min_copy_usd=Decimal("500"))
    state: dict = {}
    await strat.on_event(_snap("m1", "a"), state)
    sigs = await strat.on_event(
        _activity("m1", "a", wallet="sharp1", side="BUY", usd_value="100"),
        state,
    )
    assert sigs == []


@pytest.mark.asyncio
async def test_size_scaled_by_copy_ratio_and_capped():
    """copy_ratio scales whale size; max_size_per_trade_usd caps notional."""
    strat = WhaleCopyEod(
        tracked_wallets={"sharp1"},
        copy_ratio=Decimal("0.10"),
        max_size_per_trade_usd=Decimal("100"),
    )
    state: dict = {}
    await strat.on_event(_snap("m1", "a", ask="0.50"), state)
    # whale traded 1000 tokens — copy_ratio 10% → would be 100 tokens
    # but cap = $100 / 0.50 = 200. Min = 100.
    sigs = await strat.on_event(
        _activity("m1", "a", wallet="sharp1", side="BUY", size="1000"), state)
    assert sigs[0].size == Decimal("100.00")

    # Reset state, very large whale → cap binds
    strat2 = WhaleCopyEod(
        tracked_wallets={"sharp1"},
        copy_ratio=Decimal("0.10"),
        max_size_per_trade_usd=Decimal("100"),
    )
    state2: dict = {}
    await strat2.on_event(_snap("m1", "a", ask="0.50"), state2)
    sigs = await strat2.on_event(
        _activity("m1", "a", wallet="sharp1", side="BUY", size="100000"), state2)
    # whale 100k * 0.1 = 10k; cap 100/0.5 = 200. Min = 200.
    assert sigs[0].size == Decimal("200.00")


@pytest.mark.asyncio
async def test_cooldown_blocks_repeat():
    strat = WhaleCopyEod(tracked_wallets={"sharp1"}, wallet_market_cooldown_secs=300)
    state: dict = {}
    base = datetime(2026, 4, 30, 12, tzinfo=UTC)
    await strat.on_event(_snap("m1", "a"), state)
    sigs1 = await strat.on_event(
        _activity("m1", "a", wallet="sharp1", side="BUY", ts=base), state)
    assert len(sigs1) == 1

    # Same wallet, same market, 60s later — within cooldown
    sigs2 = await strat.on_event(
        _activity("m1", "a", wallet="sharp1", side="BUY", ts=base + timedelta(seconds=60)), state)
    assert sigs2 == []

    # 6 minutes later — past cooldown
    sigs3 = await strat.on_event(
        _activity("m1", "a", wallet="sharp1", side="BUY", ts=base + timedelta(seconds=400)), state)
    assert len(sigs3) == 1


@pytest.mark.asyncio
async def test_falls_back_to_whale_price_without_book():
    strat = WhaleCopyEod(tracked_wallets={"sharp1"})
    state: dict = {}
    # No book snapshot before activity
    sigs = await strat.on_event(
        _activity("m1", "a", wallet="sharp1", side="BUY", price="0.50"), state)
    assert len(sigs) == 1
    assert sigs[0].metadata["ref_price"] == "0.50"


@pytest.mark.asyncio
async def test_concurrent_cap():
    strat = WhaleCopyEod(tracked_wallets={"sharp1"}, max_concurrent_positions=1)
    state: dict = {}
    await strat.on_event(_snap("m1", "a"), state)
    sigs1 = await strat.on_event(
        _activity("m1", "a", wallet="sharp1", side="BUY"), state)
    assert len(sigs1) == 1

    await strat.on_event(_snap("m2", "b"), state)
    sigs2 = await strat.on_event(
        _activity("m2", "b", wallet="sharp1", side="BUY"), state)
    assert sigs2 == []


@pytest.mark.asyncio
async def test_invalid_side_skipped():
    strat = WhaleCopyEod(tracked_wallets={"sharp1"})
    state: dict = {}
    await strat.on_event(_snap("m1", "a"), state)
    sigs = await strat.on_event(
        _activity("m1", "a", wallet="sharp1", side="HOLD"), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_ignores_non_polymarket_venue():
    strat = WhaleCopyEod(tracked_wallets={"sharp1"})
    state: dict = {}
    ev = MarketEvent.make(
        event_type=EventType.ACTIVITY_TRADE,
        venue="kalshi",
        payload={"wallet": "sharp1", "side": "BUY", "size": "100",
                 "price": "0.50", "usd_value": "1000"},
        market_id="m", asset_id="a",
    )
    sigs = await strat.on_event(ev, state)
    assert sigs == []
