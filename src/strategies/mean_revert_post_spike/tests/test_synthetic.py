"""Synthetic-event tests for mean_revert_post_spike."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.core.events import EventType, MarketEvent, Side
from src.strategies.mean_revert_post_spike.strategy import MeanRevertPostSpike


def _snap(market_id: str, asset_id: str, bid: str, ask: str,
          ts: datetime | None = None) -> MarketEvent:
    return MarketEvent(
        event_id=__import__("uuid").uuid4(),
        event_type=EventType.BOOK_SNAPSHOT,
        venue="polymarket",
        market_id=market_id,
        asset_id=asset_id,
        ts=ts or datetime.now(tz=UTC),
        payload={"asks": [{"price": ask, "size": "100"}],
                 "bids": [{"price": bid, "size": "100"}]},
    )


@pytest.mark.asyncio
async def test_fades_after_spike_on_paired_asset():
    strat = MeanRevertPostSpike(spike_threshold_pct=Decimal("0.10"))
    state: dict = {}
    base = datetime(2026, 4, 30, 12, tzinfo=UTC)

    # Initialize both assets — A at 0.50, B at 0.50
    await strat.on_event(_snap("m1", "a", "0.49", "0.51", ts=base), state)
    await strat.on_event(_snap("m1", "b", "0.49", "0.51", ts=base), state)

    # 90s later: A spikes up to 0.65 (+30% on mid). B's price would have
    # dropped, but in our test we update B independently.
    await strat.on_event(_snap("m1", "b", "0.34", "0.36", ts=base + timedelta(seconds=90)), state)
    sigs = await strat.on_event(
        _snap("m1", "a", "0.64", "0.66", ts=base + timedelta(seconds=90)), state)
    assert len(sigs) == 1
    assert sigs[0].asset_id == "b"
    assert sigs[0].side == Side.BUY


@pytest.mark.asyncio
async def test_below_threshold_does_not_fire():
    strat = MeanRevertPostSpike(spike_threshold_pct=Decimal("0.10"))
    state: dict = {}
    base = datetime(2026, 4, 30, 12, tzinfo=UTC)

    await strat.on_event(_snap("m1", "a", "0.49", "0.51", ts=base), state)
    await strat.on_event(_snap("m1", "b", "0.49", "0.51", ts=base), state)

    # Only +5% move
    await strat.on_event(_snap("m1", "b", "0.46", "0.48", ts=base + timedelta(seconds=60)), state)
    sigs = await strat.on_event(
        _snap("m1", "a", "0.51", "0.53", ts=base + timedelta(seconds=60)), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_no_paired_asset_does_not_fire():
    strat = MeanRevertPostSpike()
    state: dict = {}
    base = datetime(2026, 4, 30, 12, tzinfo=UTC)

    # Only one asset observed
    await strat.on_event(_snap("m1", "a", "0.49", "0.51", ts=base), state)
    sigs = await strat.on_event(
        _snap("m1", "a", "0.65", "0.66", ts=base + timedelta(seconds=60)), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_paired_asset_outside_band_does_not_fire():
    strat = MeanRevertPostSpike(
        spike_threshold_pct=Decimal("0.10"),
        min_tradeable_price=Decimal("0.10"),
        max_tradeable_price=Decimal("0.80"),
    )
    state: dict = {}
    base = datetime(2026, 4, 30, 12, tzinfo=UTC)
    await strat.on_event(_snap("m1", "a", "0.94", "0.95", ts=base), state)
    # Paired asset at 0.04 (below floor)
    await strat.on_event(_snap("m1", "b", "0.03", "0.04", ts=base), state)
    sigs = await strat.on_event(
        _snap("m1", "a", "0.83", "0.84", ts=base + timedelta(seconds=60)), state)
    # spike on 'a' from 0.945 → 0.835 = -11.6%, but pair 'b' is below floor
    assert sigs == []


@pytest.mark.asyncio
async def test_cooldown_blocks_repeat_fade():
    strat = MeanRevertPostSpike(spike_threshold_pct=Decimal("0.10"),
                                  fade_cooldown_secs=300)
    state: dict = {}
    base = datetime(2026, 4, 30, 12, tzinfo=UTC)
    await strat.on_event(_snap("m1", "a", "0.49", "0.51", ts=base), state)
    await strat.on_event(_snap("m1", "b", "0.49", "0.51", ts=base), state)
    await strat.on_event(_snap("m1", "b", "0.34", "0.36", ts=base + timedelta(seconds=60)), state)
    sigs1 = await strat.on_event(
        _snap("m1", "a", "0.64", "0.66", ts=base + timedelta(seconds=60)), state)
    assert len(sigs1) == 1

    # Same market, even bigger spike still shouldn't re-fire (cooldown)
    sigs2 = await strat.on_event(
        _snap("m1", "a", "0.74", "0.76", ts=base + timedelta(seconds=120)), state)
    assert sigs2 == []


@pytest.mark.asyncio
async def test_size_inversely_proportional_to_paired_ask():
    strat = MeanRevertPostSpike(target_notional_usd=Decimal("50"),
                                  spike_threshold_pct=Decimal("0.10"))
    state: dict = {}
    base = datetime(2026, 4, 30, 12, tzinfo=UTC)
    await strat.on_event(_snap("m1", "a", "0.49", "0.51", ts=base), state)
    await strat.on_event(_snap("m1", "b", "0.49", "0.51", ts=base), state)
    await strat.on_event(_snap("m1", "b", "0.24", "0.25", ts=base + timedelta(seconds=60)), state)
    sigs = await strat.on_event(
        _snap("m1", "a", "0.74", "0.75", ts=base + timedelta(seconds=60)), state)
    # Paired ask = 0.25; size = 50/0.25 = 200
    assert sigs[0].size == Decimal("200.00")
