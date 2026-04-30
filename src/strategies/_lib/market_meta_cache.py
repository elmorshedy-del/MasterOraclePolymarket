"""Helper: cache MARKET_META events into per-strategy state.

Strategies that need market metadata (category, end_time, asset_ids count,
24h volume) include ``EventType.MARKET_META`` in ``required_event_types()``
and call ``apply(state, event)`` on each event.

Returns the cached metadata dict for any market_id via ``get(state, mid)``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.core.events import EventType, MarketEvent


def apply(state: dict[str, Any], event: MarketEvent) -> bool:
    if event.event_type != EventType.MARKET_META:
        return False
    if event.market_id is None:
        return False

    cache: dict[str, dict[str, Any]] = state.setdefault("_market_meta", {})
    payload = dict(event.payload)
    end_iso = payload.get("end_time")
    if isinstance(end_iso, str):
        try:
            payload["end_time"] = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        except ValueError:
            payload["end_time"] = None
    cache[event.market_id] = payload
    return True


def get(state: dict[str, Any], market_id: str) -> dict[str, Any] | None:
    return state.get("_market_meta", {}).get(market_id)


def category(state: dict[str, Any], market_id: str) -> str | None:
    m = get(state, market_id)
    if m is None:
        return None
    cat = m.get("category")
    return cat.lower() if isinstance(cat, str) else None


def end_time(state: dict[str, Any], market_id: str) -> datetime | None:
    m = get(state, market_id)
    if m is None:
        return None
    end = m.get("end_time")
    return end if isinstance(end, datetime) else None


def volume_24h(state: dict[str, Any], market_id: str) -> float | None:
    m = get(state, market_id)
    if m is None:
        return None
    extra = m.get("tags_extra") or {}
    raw = extra.get("volume_24h")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
