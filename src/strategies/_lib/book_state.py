"""Tiny in-strategy book reconstruction from MarketEvents.

Strategies that need best-bid / best-ask / depth at a level should NOT touch
the platform's shared OrderBookStore (that breaks replay determinism).
Instead they call ``apply(state, event)`` once per relevant event; the
helper keeps a per-asset book in ``state['_books']`` derived purely from
the event stream.

Methods:
  - apply(state, event): updates state from BOOK_SNAPSHOT or BOOK_DELTA
  - best_ask(state, asset_id) / best_bid(state, asset_id)
  - depth_top_usd(state, asset_id): mid * (best_bid_size + best_ask_size)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.core.events import EventType, MarketEvent


def apply(state: dict[str, Any], event: MarketEvent) -> bool:
    """Update per-asset book in state['_books']. Returns True if applied."""
    if event.market_id is None or event.asset_id is None:
        return False
    if event.event_type not in (EventType.BOOK_SNAPSHOT, EventType.BOOK_DELTA):
        return False

    books: dict[str, dict[str, Any]] = state.setdefault("_books", {})

    if event.event_type == EventType.BOOK_SNAPSHOT:
        # Defensive: payload may contain None or non-list values for bids/asks
        # (corrupt vendor message, MARKET_META misrouted here, test fixtures, ...).
        raw_bids = event.payload.get("bids")
        raw_asks = event.payload.get("asks")
        if not isinstance(raw_bids, list):
            raw_bids = []
        if not isinstance(raw_asks, list):
            raw_asks = []
        bids = _parse_levels(raw_bids)
        asks = _parse_levels(raw_asks)
        bids.sort(key=lambda x: x[0], reverse=True)
        asks.sort(key=lambda x: x[0])
        books[event.asset_id] = {
            "bids": bids,
            "asks": asks,
            "market_id": event.market_id,
            "last_ts": event.ts,
        }
        return True

    book = books.get(event.asset_id)
    if book is None:
        return False  # need snapshot first
    from src.strategies._lib.parsing import safe_decimal
    raw_changes = event.payload.get("changes")
    if not isinstance(raw_changes, list):
        return False
    for ch in raw_changes:
        if not isinstance(ch, dict):
            continue
        side = (ch.get("side") or "").lower()
        price = safe_decimal(ch.get("price"))
        size = safe_decimal(ch.get("size"))
        if price is None or size is None:
            continue
        levels = book["bids"] if side == "buy" else book["asks"]
        for i, (p, _s) in enumerate(levels):
            if p == price:
                if size <= 0:
                    levels.pop(i)
                else:
                    levels[i] = (price, size)
                break
        else:
            if size > 0:
                levels.append((price, size))
        if side == "buy":
            book["bids"] = sorted(levels, key=lambda x: x[0], reverse=True)
        else:
            book["asks"] = sorted(levels, key=lambda x: x[0])
    book["last_ts"] = event.ts
    return True


def _parse_levels(raw: list[dict]) -> list[tuple[Decimal, Decimal]]:
    """Parse a list of {price, size} dicts. Skips any malformed entries
    (missing keys, None values, non-numeric strings — Decimal(str(None))
    raises InvalidOperation, NOT ValueError, hence the broad except)."""
    from src.strategies._lib.parsing import safe_decimal
    out: list[tuple[Decimal, Decimal]] = []
    for level in raw:
        if not isinstance(level, dict):
            continue
        p = safe_decimal(level.get("price"))
        s = safe_decimal(level.get("size"))
        if p is None or s is None:
            continue
        if s > 0:
            out.append((p, s))
    return out


def book(state: dict[str, Any], asset_id: str) -> dict[str, Any] | None:
    return state.get("_books", {}).get(asset_id)


def best_ask(state: dict[str, Any], asset_id: str) -> Decimal | None:
    b = book(state, asset_id)
    if b is None or not b.get("asks"):
        return None
    return b["asks"][0][0]


def best_ask_size(state: dict[str, Any], asset_id: str) -> Decimal | None:
    b = book(state, asset_id)
    if b is None or not b.get("asks"):
        return None
    return b["asks"][0][1]


def best_bid(state: dict[str, Any], asset_id: str) -> Decimal | None:
    b = book(state, asset_id)
    if b is None or not b.get("bids"):
        return None
    return b["bids"][0][0]


def best_bid_size(state: dict[str, Any], asset_id: str) -> Decimal | None:
    b = book(state, asset_id)
    if b is None or not b.get("bids"):
        return None
    return b["bids"][0][1]


def mid(state: dict[str, Any], asset_id: str) -> Decimal | None:
    a = best_ask(state, asset_id)
    b = best_bid(state, asset_id)
    if a is None or b is None:
        return None
    return (a + b) / Decimal(2)


def tob_depth_usd(state: dict[str, Any], asset_id: str) -> Decimal | None:
    a = best_ask(state, asset_id)
    a_sz = best_ask_size(state, asset_id)
    b = best_bid(state, asset_id)
    b_sz = best_bid_size(state, asset_id)
    if a is None or b is None or a_sz is None or b_sz is None:
        return None
    m = (a + b) / Decimal(2)
    return (a_sz + b_sz) * m
