"""Robustness against malformed event payloads — every strategy must shrug
off bad input rather than crash the runner.

Decimal pitfall driving most of these tests:
  Decimal(str(None))               → InvalidOperation
  Decimal(str("not-a-number"))     → InvalidOperation
  Decimal(str(""))                 → InvalidOperation

A naïve ``except (TypeError, ValueError)`` MISSES InvalidOperation.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.core import plugin_loader
from src.core.events import EventType, MarketEvent
from src.strategies._lib import book_state
from src.strategies._lib.parsing import safe_decimal

# ---------------------------------------------------------------------------
# safe_decimal: the helper itself
# ---------------------------------------------------------------------------


def test_safe_decimal_handles_none():
    assert safe_decimal(None) is None


def test_safe_decimal_handles_garbage():
    assert safe_decimal("not-a-number") is None
    assert safe_decimal("") is None
    assert safe_decimal({}) is None
    assert safe_decimal([]) is None


def test_safe_decimal_passes_real_values():
    assert safe_decimal("0.50") == Decimal("0.50")
    assert safe_decimal(0.5) == Decimal("0.5")
    assert safe_decimal(Decimal("0.42")) == Decimal("0.42")


# ---------------------------------------------------------------------------
# book_state: malformed snapshots / deltas don't crash
# ---------------------------------------------------------------------------


def _ev(et, payload, market="m1", asset="a"):
    return MarketEvent.make(
        event_type=et, venue="polymarket",
        payload=payload, market_id=market, asset_id=asset,
    )


def test_book_state_apply_skips_malformed_levels():
    state: dict = {}
    book_state.apply(state, _ev(EventType.BOOK_SNAPSHOT, {
        "asks": [
            {"price": "0.50", "size": "100"},     # ok
            {"price": None, "size": "50"},         # missing price
            {"price": "garbage", "size": "10"},    # garbage price
            {"size": "20"},                        # missing key
            "not even a dict",                     # type error
            {"price": "0.51", "size": "0"},        # zero size, dropped
        ],
        "bids": [{"price": "0.49", "size": "100"}],
    }))
    b = book_state.book(state, "a")
    assert b is not None
    assert b["asks"] == [(Decimal("0.50"), Decimal("100"))]
    assert b["bids"] == [(Decimal("0.49"), Decimal("100"))]


def test_book_state_apply_delta_with_garbage_does_not_crash():
    state: dict = {}
    book_state.apply(state, _ev(EventType.BOOK_SNAPSHOT, {
        "asks": [{"price": "0.50", "size": "100"}],
        "bids": [{"price": "0.49", "size": "100"}],
    }))
    book_state.apply(state, _ev(EventType.BOOK_DELTA, {
        "changes": [
            {"side": "sell", "price": None, "size": "10"},
            {"side": "sell", "price": "0.50", "size": "0"},   # remove the level
            "not a dict",
            {"side": "buy", "price": "0.48", "size": "garbage"},
        ],
    }))
    # The valid 'remove level' should have applied
    b = book_state.book(state, "a")
    assert b["asks"] == []   # 0.50 removed by valid change


# ---------------------------------------------------------------------------
# Per-strategy: feeding a stream of malformed events must not raise
# ---------------------------------------------------------------------------


_MALFORMED_STREAM = [
    _ev(EventType.MARKET_META, {"asset_ids": ["a", "b"], "category": "weather",
                                  "tags_extra": {"volume_24h": 25000},
                                  "end_time": (datetime(2026, 5, 5, 13, tzinfo=UTC)).isoformat()}),
    _ev(EventType.BOOK_SNAPSHOT, {"asks": [{"price": None, "size": None}], "bids": []}),
    _ev(EventType.BOOK_SNAPSHOT, {"asks": "not a list", "bids": None}),
    _ev(EventType.BOOK_SNAPSHOT, {}),
    _ev(EventType.BOOK_DELTA, {"changes": [{"price": "garbage"}]}),
    _ev(EventType.TRADE_PRINT, {"price": None, "size": None}),
    _ev(EventType.TRADE_PRINT, {"price": "abc"}),
    _ev(EventType.TRADE_PRINT, {}),
    _ev(EventType.ACTIVITY_TRADE, {"wallet": None, "side": None}),
    _ev(EventType.ACTIVITY_TRADE, {"wallet": "coldmath", "side": "BUY",
                                     "size": "garbage", "usd_value": None, "price": None}),
    _ev(EventType.ACTIVITY_TRADE, {"wallet": "coldmath", "side": "SIDEWAYS",
                                     "size": "100", "usd_value": "200", "price": "0.5"}),
]


def _strategies():
    return [(p.name, p.instance) for p in plugin_loader.discover_all(
        __import__("pathlib").Path(__file__).resolve().parents[2]
    ) if p.kind == "strategy"]


@pytest.mark.parametrize("name,inst", _strategies())
def test_strategy_does_not_crash_on_malformed_stream(name, inst):
    """Feeds a stream of payloads with None/garbage/missing fields. Asserts
    the strategy raises NOTHING and only emits well-formed signals."""
    state: dict = {"sleeve_id": f"malformed__{name}", "config_id": "default"}

    async def _drive():
        emitted = []
        for ev in _MALFORMED_STREAM:
            try:
                sigs = await inst.on_event(ev, state)
            except Exception as exc:
                pytest.fail(f"{name} crashed on malformed event {ev.event_type}: {exc!r}")
            emitted.extend(sigs)
        return emitted

    sigs = asyncio.run(_drive())
    for s in sigs:
        # Anything emitted must still be well-formed
        assert s.size > 0
        assert s.market_id and s.asset_id
        if s.price is not None:
            assert s.price > 0
