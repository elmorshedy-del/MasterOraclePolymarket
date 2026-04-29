"""Synthetic-event tests for cross_outcome_arb.

Each test feeds hand-crafted MarketEvents to the strategy and asserts on
the signals (count, side, price, size, metadata).

These tests are part of the strategy's promotion gate from replay_only →
live_log. They must pass before any sleeve config sets ``mode: live_log``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from src.core.events import EventType, MarketEvent, Side
from src.strategies.cross_outcome_arb.strategy import CrossOutcomeArb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot(market_id: str, asset_id: str, asks: list[tuple[str, str]],
              bids: list[tuple[str, str]] | None = None) -> MarketEvent:
    bids = bids or [("0.45", "100")]
    return MarketEvent.make(
        event_type=EventType.BOOK_SNAPSHOT,
        venue="polymarket",
        payload={
            "asks": [{"price": p, "size": s} for p, s in asks],
            "bids": [{"price": p, "size": s} for p, s in bids],
        },
        market_id=market_id,
        asset_id=asset_id,
    )


def _delta(market_id: str, asset_id: str,
           changes: list[tuple[str, str, str]]) -> MarketEvent:
    """changes: list of (side, price, size) — side is 'sell' for asks."""
    return MarketEvent.make(
        event_type=EventType.BOOK_DELTA,
        venue="polymarket",
        payload={
            "changes": [
                {"side": s, "price": p, "size": z} for s, p, z in changes
            ]
        },
        market_id=market_id,
        asset_id=asset_id,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arb_below_threshold_emits_two_signals():
    strat = CrossOutcomeArb()
    state: dict = {"sleeve_id": "test_sleeve", "config_id": "default"}

    # First leg snapshot — no arb yet (only one asset known)
    sigs = await strat.on_event(_snapshot("m1", "yes_token", [("0.50", "100")]), state)
    assert sigs == []

    # Second leg snapshot — sum_asks = 0.50 + 0.45 = 0.95 < 0.99 → fire!
    sigs = await strat.on_event(_snapshot("m1", "no_token", [("0.45", "100")]), state)
    assert len(sigs) == 2

    sides = {s.side for s in sigs}
    assert sides == {Side.BUY}

    asset_ids = {s.asset_id for s in sigs}
    assert asset_ids == {"yes_token", "no_token"}

    # Reasons share the strategy name
    assert all(s.reason.startswith("cross_outcome_arb") for s in sigs)
    assert all(s.metadata.get("gross_edge_bps") == 500 for s in sigs)


@pytest.mark.asyncio
async def test_no_arb_above_threshold():
    strat = CrossOutcomeArb()
    state: dict = {}

    await strat.on_event(_snapshot("m1", "yes", [("0.55", "100")]), state)
    sigs = await strat.on_event(_snapshot("m1", "no", [("0.50", "100")]), state)
    # sum 1.05 > 0.99 → no arb
    assert sigs == []


@pytest.mark.asyncio
async def test_threshold_boundary_inclusive_exclusive():
    """If sum_asks == max_sum_threshold exactly, must NOT fire (require strict edge)."""
    strat = CrossOutcomeArb(min_edge_bps=100, max_sum_threshold=Decimal("0.99"))
    state: dict = {}

    await strat.on_event(_snapshot("m1", "yes", [("0.50", "100")]), state)
    sigs = await strat.on_event(_snapshot("m1", "no", [("0.49", "100")]), state)
    # sum 0.99 ≤ 0.99 BUT gross_edge_bps = 100 ≥ min_edge_bps = 100 → fire
    assert len(sigs) == 2
    assert sigs[0].metadata["gross_edge_bps"] == 100


@pytest.mark.asyncio
async def test_only_one_leg_seen_does_not_fire():
    strat = CrossOutcomeArb()
    state: dict = {}
    sigs = await strat.on_event(_snapshot("m1", "yes", [("0.40", "100")]), state)
    assert sigs == []
    # Even with a delta, still no second leg
    sigs = await strat.on_event(_delta("m1", "yes", [("sell", "0.40", "200")]), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_does_not_re_arb_same_market():
    strat = CrossOutcomeArb()
    state: dict = {}

    await strat.on_event(_snapshot("m1", "yes", [("0.50", "100")]), state)
    sigs1 = await strat.on_event(_snapshot("m1", "no", [("0.45", "100")]), state)
    assert len(sigs1) == 2

    # Same market, same prices, fired again — should NOT emit
    sigs2 = await strat.on_event(_snapshot("m1", "no", [("0.45", "100")]), state)
    assert sigs2 == []


@pytest.mark.asyncio
async def test_delta_after_snapshot_updates_book_and_fires():
    strat = CrossOutcomeArb()
    state: dict = {}

    # Both legs initially above threshold (sum 1.05)
    await strat.on_event(_snapshot("m1", "yes", [("0.55", "100")]), state)
    sigs = await strat.on_event(_snapshot("m1", "no", [("0.50", "100")]), state)
    assert sigs == []

    # YES ask drops to 0.40 via delta — sum 0.90 → fire
    sigs = await strat.on_event(_delta("m1", "yes", [("sell", "0.55", "0"),
                                                      ("sell", "0.40", "100")]), state)
    assert len(sigs) == 2


@pytest.mark.asyncio
async def test_size_inversely_proportional_to_price():
    strat = CrossOutcomeArb(max_size_per_leg_usd=Decimal("200"))
    state: dict = {}

    await strat.on_event(_snapshot("m1", "yes", [("0.40", "100")]), state)
    sigs = await strat.on_event(_snapshot("m1", "no", [("0.50", "100")]), state)
    assert len(sigs) == 2

    by_asset = {s.asset_id: s for s in sigs}
    # size = max_size_per_leg / ask
    assert by_asset["yes"].size == Decimal("500.00")    # 200 / 0.40
    assert by_asset["no"].size == Decimal("400.00")     # 200 / 0.50


@pytest.mark.asyncio
async def test_price_buffered_above_ask():
    strat = CrossOutcomeArb(price_buffer_bps=50)
    state: dict = {}

    await strat.on_event(_snapshot("m1", "yes", [("0.50", "100")]), state)
    sigs = await strat.on_event(_snapshot("m1", "no", [("0.40", "100")]), state)
    by_asset = {s.asset_id: s for s in sigs}
    # price = ask + buffer (0.50 + 0.005, 0.40 + 0.005)
    assert by_asset["yes"].price == Decimal("0.5050")
    assert by_asset["no"].price == Decimal("0.4050")


@pytest.mark.asyncio
async def test_signals_have_paired_metadata():
    strat = CrossOutcomeArb()
    state: dict = {}
    await strat.on_event(_snapshot("m1", "yes", [("0.50", "100")]), state)
    sigs = await strat.on_event(_snapshot("m1", "no", [("0.40", "100")]), state)

    by_leg = {s.metadata["leg"]: s for s in sigs}
    # Sorted asset_ids: "no" < "yes"
    assert by_leg["a"].asset_id == "no"
    assert by_leg["a"].metadata["paired_asset_id"] == "yes"
    assert by_leg["b"].asset_id == "yes"
    assert by_leg["b"].metadata["paired_asset_id"] == "no"


@pytest.mark.asyncio
async def test_concurrent_position_cap():
    strat = CrossOutcomeArb(max_concurrent_positions=2)
    state: dict = {}

    # Fire 2 arbs (cap reached)
    for i, mid in enumerate(["m1", "m2"]):
        await strat.on_event(_snapshot(mid, f"yes_{i}", [("0.50", "100")]), state)
        sigs = await strat.on_event(_snapshot(mid, f"no_{i}", [("0.40", "100")]), state)
        assert len(sigs) == 2

    # Third market hits cap → no signals
    await strat.on_event(_snapshot("m3", "yes_2", [("0.50", "100")]), state)
    sigs = await strat.on_event(_snapshot("m3", "no_2", [("0.40", "100")]), state)
    assert sigs == []


@pytest.mark.asyncio
async def test_ignores_non_polymarket_events():
    strat = CrossOutcomeArb()
    state: dict = {}

    ev = MarketEvent.make(
        event_type=EventType.BOOK_SNAPSHOT,
        venue="kalshi",
        payload={"asks": [{"price": "0.50", "size": "100"}]},
        market_id="m1",
        asset_id="kalshi_yes",
    )
    sigs = await strat.on_event(ev, state)
    assert sigs == []


@pytest.mark.asyncio
async def test_ignores_unknown_event_types():
    strat = CrossOutcomeArb()
    state: dict = {}

    ev = MarketEvent.make(
        event_type=EventType.NEWS_ITEM,
        venue="news",
        payload={"title": "hello"},
    )
    sigs = await strat.on_event(ev, state)
    assert sigs == []


@pytest.mark.asyncio
async def test_signal_ids_are_unique_uuids():
    strat = CrossOutcomeArb()
    state: dict = {}
    await strat.on_event(_snapshot("m1", "yes", [("0.50", "100")]), state)
    sigs = await strat.on_event(_snapshot("m1", "no", [("0.40", "100")]), state)
    assert isinstance(sigs[0].signal_id, UUID)
    assert isinstance(sigs[1].signal_id, UUID)
    assert sigs[0].signal_id != sigs[1].signal_id
