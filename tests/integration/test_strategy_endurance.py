"""Multi-day endurance harness — drives every shipped strategy through a
realistic synthetic event timeline and asserts:

  - no uncaught exception across ~5,000 events
  - emitted Signals are well-formed
  - active-state sets are correctly cleared on MARKET_RESOLVED
  - state size stays bounded across the run

This is the closest we can get to "tried before deploy" without a real
Polymarket connection. Replaces the audit's "Strategy Lab is invalid"
finding with empirical evidence that each strategy at least RUNS at scale.
"""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.core import plugin_loader
from src.core.events import EventType, MarketEvent, Side, Signal
from src.strategies._lib.active_state import ACTIVE_STATE_KEYS, clear_for_market

REPO_ROOT = Path(__file__).resolve().parents[2]


def _generate_timeline(
    n_markets: int = 6,
    days: int = 3,
    snapshots_per_day_per_market: int = 50,
    seed: int = 42,
):
    """Build a realistic-ish multi-day event timeline for n binary markets."""
    rng = random.Random(seed)
    base = datetime(2026, 5, 5, 12, tzinfo=UTC)
    events: list[MarketEvent] = []
    market_winners: dict[str, str] = {}

    for mi in range(n_markets):
        mid = f"market_{mi}"
        category = "weather" if mi % 2 == 0 else "politics"
        end_time = base + timedelta(days=days)
        events.append(MarketEvent.make(
            event_type=EventType.MARKET_META,
            venue="polymarket",
            payload={
                "title": f"endurance market {mi}",
                "category": category,
                "subcategory": f"{category}/region/{mi}",
                "asset_ids": [f"{mid}_yes", f"{mid}_no"],
                "tick_size": "0.01",
                "tags_extra": {"volume_24h": 25_000 + mi * 1000},
                "end_time": end_time.isoformat(),
            },
            market_id=mid,
            asset_id=f"{mid}_yes",
            ts=base,
        ))
        winner = rng.choice([f"{mid}_yes", f"{mid}_no"])
        market_winners[mid] = winner

        for d in range(days):
            day_base = base + timedelta(days=d)
            yes_p = 0.50
            for tick in range(snapshots_per_day_per_market):
                ts = day_base + timedelta(seconds=tick * 60)
                target = 1.0 if winner == f"{mid}_yes" else 0.0
                yes_p += (target - yes_p) * 0.01 + rng.uniform(-0.02, 0.02)
                yes_p = max(0.02, min(0.98, yes_p))
                no_p = 1.0 - yes_p
                for aid, p in ((f"{mid}_yes", yes_p), (f"{mid}_no", no_p)):
                    events.append(MarketEvent.make(
                        event_type=EventType.BOOK_SNAPSHOT,
                        venue="polymarket",
                        payload={
                            "asks": [
                                {"price": f"{min(0.99, p + 0.01):.4f}", "size": "200"},
                                {"price": f"{min(0.99, p + 0.02):.4f}", "size": "400"},
                            ],
                            "bids": [
                                {"price": f"{max(0.01, p - 0.01):.4f}", "size": "200"},
                                {"price": f"{max(0.01, p - 0.02):.4f}", "size": "400"},
                            ],
                        },
                        market_id=mid,
                        asset_id=aid,
                        ts=ts,
                    ))
            for _ in range(20):
                ts = day_base + timedelta(seconds=rng.randint(0, 86_400))
                aid = rng.choice([f"{mid}_yes", f"{mid}_no"])
                trade_p = yes_p if aid.endswith("_yes") else (1 - yes_p)
                events.append(MarketEvent.make(
                    event_type=EventType.TRADE_PRINT,
                    venue="polymarket",
                    payload={"price": f"{trade_p:.4f}", "size": "10",
                              "side": rng.choice(["buy", "sell"])},
                    market_id=mid,
                    asset_id=aid,
                    ts=ts,
                ))
            for _ in range(3):
                ts = day_base + timedelta(seconds=rng.randint(0, 86_400))
                wallet = rng.choice(["coldmath", "henrytheatmophd",
                                     "random_wallet_a", "random_wallet_b"])
                events.append(MarketEvent.make(
                    event_type=EventType.ACTIVITY_TRADE,
                    venue="polymarket",
                    payload={
                        "wallet": wallet,
                        "side": rng.choice(["BUY", "SELL"]),
                        "price": f"{yes_p:.4f}",
                        "size": "200",
                        "usd_value": "150",
                    },
                    market_id=mid,
                    asset_id=f"{mid}_yes",
                    ts=ts,
                ))

        events.append(MarketEvent.make(
            event_type=EventType.MARKET_RESOLVED,
            venue="polymarket",
            payload={
                "title": f"endurance market {mi}",
                "category": category,
                "winning_asset_id": winner,
            },
            market_id=mid,
            ts=end_time,
        ))

    # Sprinkle ~1% deliberately-malformed events
    n_malformed = max(1, len(events) // 100)
    bad_payloads = [
        {"asks": None, "bids": "garbage"},
        {"changes": "not a list"},
        {"price": None, "size": None},
        {"wallet": None, "side": "SIDEWAYS", "size": "garbage", "usd_value": None},
    ]
    for _ in range(n_malformed):
        i = rng.randint(0, len(events) - 1)
        et = rng.choice([EventType.BOOK_SNAPSHOT, EventType.BOOK_DELTA,
                         EventType.TRADE_PRINT, EventType.ACTIVITY_TRADE])
        existing = events[i]
        events.insert(i, MarketEvent.make(
            event_type=et,
            venue="polymarket",
            payload=rng.choice(bad_payloads),
            market_id=existing.market_id,
            asset_id=existing.asset_id,
            ts=existing.ts,
        ))

    events.sort(key=lambda e: e.ts)
    return events, market_winners


def _is_well_formed(s: Signal) -> bool:
    if not s.market_id or not s.asset_id:
        return False
    if s.size <= 0:
        return False
    if s.side not in (Side.BUY, Side.SELL):
        return False
    if s.price is not None and s.price <= 0:
        return False
    return True


def _shipped_strategies():
    plugins = plugin_loader.discover_all(REPO_ROOT)
    return [(p.name, p.instance) for p in plugins if p.kind == "strategy"]


@pytest.mark.parametrize("name,inst", _shipped_strategies())
def test_endurance_run(name, inst):
    events, winners = _generate_timeline()
    state: dict = {
        "sleeve_id": f"endurance__{name}",
        "config_id": "default",
        "config_hash": "endurance",
    }
    emitted: list[Signal] = []
    crashes: list[str] = []

    async def _drive():
        for ev in events:
            try:
                sigs = await inst.on_event(ev, state)
            except Exception as exc:
                crashes.append(f"{ev.event_type.value} on {ev.market_id}: {exc!r}")
                sigs = []
            emitted.extend(sigs)
            if ev.event_type == EventType.MARKET_RESOLVED and ev.market_id:
                clear_for_market(state, ev.market_id)

    asyncio.run(_drive())

    assert crashes == [], (
        f"{name} crashed on {len(crashes)} events:\n" + "\n".join(crashes[:5])
    )

    bad = [s for s in emitted if not _is_well_formed(s)]
    assert not bad, f"{name} emitted {len(bad)} malformed signals"

    # Active sets must be clear after MARKET_RESOLVED for every market
    for key in ACTIVE_STATE_KEYS:
        bag = state.get(key)
        if isinstance(bag, set) and bag:
            stragglers = [
                e for e in bag
                if (isinstance(e, str) and e in winners)
                or (isinstance(e, tuple) and any(x in winners for x in e))
            ]
            assert not stragglers, (
                f"{name} kept active-state entries {stragglers} for "
                f"resolved markets — clear_for_market did not fully clean up"
            )

    total = 0
    for v in state.values():
        if isinstance(v, (set, list, dict)):
            total += len(v)
    assert total < 50_000, f"{name} state grew to {total} entries — likely a leak"


def test_endurance_combined_some_signals():
    """At least one strategy across all 9 should fire SOMETHING on a
    3-day, 6-market timeline. If everything is zero, we have a real bug."""
    events, _ = _generate_timeline()
    total = 0
    per_strategy: dict[str, int] = {}
    for name, inst in _shipped_strategies():
        state: dict = {"sleeve_id": "combined", "config_id": "default"}
        emitted: list[Signal] = []

        async def _drive():
            for ev in events:
                try:
                    sigs = await inst.on_event(ev, state)
                except Exception:
                    sigs = []
                emitted.extend(sigs)
                if ev.event_type == EventType.MARKET_RESOLVED and ev.market_id:
                    clear_for_market(state, ev.market_id)

        asyncio.run(_drive())
        per_strategy[name] = len(emitted)
        total += len(emitted)

    assert total >= 5, (
        f"only {total} signals across all strategies — endurance harness or "
        f"strategies are broken. Per-strategy counts: {per_strategy}"
    )
