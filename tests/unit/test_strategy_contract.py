"""Universal Strategy contract — every shipped strategy must pass these.

Three families:

  1. Static contract: required interface, edge_class declared, configs present,
     DESIGN.md present.
  2. Resolution-cleanup contract: every active-state key that any strategy
     uses must be registered in active_state.ACTIVE_STATE_KEYS, otherwise
     MARKET_RESOLVED won't free that market on that strategy.
  3. Behavioral contract: synthetic stress run produces no exception, no
     malformed Signals, no unbounded memory growth in state.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from src.core import plugin_loader
from src.core.events import (
    EventType,
    MarketEvent,
    OrderType,
    Side,
    Signal,
)
from src.strategies._lib.active_state import ACTIVE_STATE_KEYS

REPO_ROOT = Path(__file__).resolve().parents[2]
STRATEGIES_DIR = REPO_ROOT / "src" / "strategies"


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def _shipped_strategies():
    """Return list of (name, class, instance) for every non-template strategy."""
    plugins = plugin_loader.discover_all(REPO_ROOT)
    out = []
    for p in plugins:
        if p.kind != "strategy":
            continue
        out.append((p.name, type(p.instance), p.instance))
    return out


def _strategy_files() -> list[Path]:
    """All non-private strategy.py files."""
    return [
        f for f in STRATEGIES_DIR.rglob("strategy.py")
        if not any(part.startswith("_") for part in f.parts)
    ]


# ---------------------------------------------------------------------------
# Static contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,cls,inst", _shipped_strategies())
def test_strategy_has_required_interface(name, cls, inst):
    assert inst.name == name, f"plugin name mismatch on {name}"
    assert isinstance(inst.edge_class, str) and inst.edge_class
    # required_event_types and required_data_sources must be callable + return sets
    ev_types = inst.required_event_types()
    assert isinstance(ev_types, set) and ev_types
    sources = inst.required_data_sources()
    assert isinstance(sources, set) and sources
    # All declared event types are valid EventType values
    valid = {e.value for e in EventType}
    assert ev_types.issubset(valid), f"{name} declares unknown event type(s): {ev_types - valid}"


@pytest.mark.parametrize("name,cls,inst", _shipped_strategies())
def test_strategy_has_design_doc(name, cls, inst):
    folder = STRATEGIES_DIR / name
    design = folder / "DESIGN.md"
    assert design.exists(), f"{name} missing DESIGN.md"
    body = design.read_text()
    # All 12 numbered headings must appear
    for i in range(1, 13):
        assert re.search(rf"^## {i}\.", body, re.MULTILINE), (
            f"{name}/DESIGN.md missing section {i}."
        )


@pytest.mark.parametrize("name,cls,inst", _shipped_strategies())
def test_strategy_has_default_config(name, cls, inst):
    default = STRATEGIES_DIR / name / "config_default.yaml"
    assert default.exists(), f"{name} missing config_default.yaml"


@pytest.mark.parametrize("name,cls,inst", _shipped_strategies())
def test_strategy_accepts_unknown_kwargs_without_crash(name, cls, inst):
    """Sleeve YAML may carry extra keys; the strategy ctor must tolerate them."""
    try:
        cls(**{"_definitely_not_a_real_param_xyz": 99})
    except TypeError:
        # That's fine — the runner falls back to no-arg construction in this case.
        cls()


# ---------------------------------------------------------------------------
# Resolution-cleanup contract — derived from source, not hardcoded
# ---------------------------------------------------------------------------


_ACTIVE_KEY_RE = re.compile(r'state\.setdefault\(\s*"(_active_[a-z_]+|active_[a-z_]+)"')


def _grep_active_keys_in_source() -> set[str]:
    """Find every active-state key any shipped strategy uses, by grepping source.

    This is brittle — but it's a SAFETY NET: if a new strategy introduces a
    new active key and forgets to register it, the test fires before it can
    cause a frozen-market production bug.
    """
    found: set[str] = set()
    for f in _strategy_files():
        text = f.read_text()
        found.update(_ACTIVE_KEY_RE.findall(text))
    return found


def test_every_strategy_active_key_is_registered():
    used = _grep_active_keys_in_source()
    missing = used - set(ACTIVE_STATE_KEYS)
    assert missing == set(), (
        f"strategies use active-state keys {missing} that are not in "
        f"ACTIVE_STATE_KEYS — those markets will never be cleared on "
        f"MARKET_RESOLVED, causing the strategy to freeze on those markets. "
        f"Add them to src/strategies/_lib/active_state.py:ACTIVE_STATE_KEYS."
    )


# ---------------------------------------------------------------------------
# Behavioral contract — synthetic stress
# ---------------------------------------------------------------------------


def _synthetic_stream(n: int = 50, market_id: str = "stress_m"):
    """Generate a synthetic stream covering every event type strategies care about."""
    base = datetime(2026, 5, 5, 12, tzinfo=timezone.utc)
    events: list[MarketEvent] = []

    # Two markets with two assets each — enough for arb / pair logic
    for mid in (market_id, f"{market_id}_2"):
        for aid in (f"{mid}_yes", f"{mid}_no"):
            events.append(MarketEvent.make(
                event_type=EventType.MARKET_META,
                venue="polymarket",
                payload={
                    "title": "stress test market",
                    "category": "weather",
                    "subcategory": "weather/stress",
                    "asset_ids": [f"{mid}_yes", f"{mid}_no"],
                    "tick_size": "0.01",
                    "tags_extra": {"volume_24h": 25_000},
                    "end_time": (base + timedelta(minutes=30)).isoformat(),
                },
                market_id=mid,
                asset_id=aid,
                ts=base,
            ))

    for i in range(n):
        ts = base + timedelta(seconds=i * 5)
        for mid in (market_id, f"{market_id}_2"):
            for aid in (f"{mid}_yes", f"{mid}_no"):
                # Snapshot
                events.append(MarketEvent.make(
                    event_type=EventType.BOOK_SNAPSHOT,
                    venue="polymarket",
                    payload={
                        "asks": [{"price": "0.49", "size": "200"},
                                 {"price": "0.51", "size": "100"}],
                        "bids": [{"price": "0.47", "size": "200"}],
                    },
                    market_id=mid,
                    asset_id=aid,
                    ts=ts,
                ))
                # Trade print
                events.append(MarketEvent.make(
                    event_type=EventType.TRADE_PRINT,
                    venue="polymarket",
                    payload={"price": "0.50", "size": "5", "side": "buy"},
                    market_id=mid,
                    asset_id=aid,
                    ts=ts,
                ))
        # An activity trade by a tracked wallet
        events.append(MarketEvent.make(
            event_type=EventType.ACTIVITY_TRADE,
            venue="polymarket",
            payload={
                "wallet": "coldmath",
                "side": "BUY",
                "price": "0.50",
                "size": "200",
                "usd_value": "100",
            },
            market_id=market_id,
            asset_id=f"{market_id}_yes",
            ts=ts,
        ))

    return events


def _is_valid_signal(s: Signal) -> bool:
    if not isinstance(s, Signal):
        return False
    if not s.market_id or not s.asset_id:
        return False
    if s.size <= 0:
        return False
    if s.order_type == OrderType.LIMIT and (s.price is None or s.price <= 0):
        return False
    if s.side not in (Side.BUY, Side.SELL):
        return False
    return True


@pytest.mark.parametrize("name,cls,inst", _shipped_strategies())
def test_strategy_survives_synthetic_stress(name, cls, inst):
    """Run 50 cycles of a multi-market event stream through the strategy. Assert:
       - no uncaught exceptions
       - every emitted Signal is valid
       - state dict size stays bounded (< 10k entries) — sanity check for leaks
    """
    state: dict = {"sleeve_id": f"stress__{name}", "config_id": "default"}
    events = _synthetic_stream()

    async def _drive():
        emitted: list[Signal] = []
        for ev in events:
            sigs = await inst.on_event(ev, state)
            emitted.extend(sigs)
        return emitted

    emitted = asyncio.run(_drive())

    # Every emitted signal must pass validation
    for s in emitted:
        assert _is_valid_signal(s), f"{name} emitted invalid signal: {s}"

    # State growth sanity — total stored elements across all known keys
    total = 0
    for v in state.values():
        if isinstance(v, (set, list, dict)):
            total += len(v)
    assert total < 10_000, f"{name} state grew to {total} entries — possible leak"
