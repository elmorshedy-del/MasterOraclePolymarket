"""Polymarket public activity feed adapter.

Polls the data-api for recent public trades and redemptions across all markets,
yielding ``ACTIVITY_TRADE`` and ``ACTIVITY_REDEMPTION`` events.

This is the data foundation for whale-copy / fade / sharp-followup strategies.
We poll because Polymarket doesn't expose this as a websocket — the activity
API is REST.

Endpoint reference: https://data-api.polymarket.com/activity
(Field names normalized below; the exact REST schema can shift, so we treat
unknown fields permissively.)
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timezone

import httpx

from src.core.events import EventType, MarketEvent, MarketMeta
from src.core.interfaces import MarketDataSource

logger = logging.getLogger(__name__)


VENUE = "polymarket"
DEFAULT_API_BASE = "https://data-api.polymarket.com"


class PolymarketActivity:
    name: str = "polymarket_activity"

    def __init__(
        self,
        api_base: str | None = None,
        poll_interval_secs: float = 5.0,
        page_size: int = 200,
        enabled: bool = True,
    ) -> None:
        self.api_base = api_base or os.environ.get("POLYMARKET_DATA_API_URL", DEFAULT_API_BASE)
        self.poll_interval_secs = poll_interval_secs
        self.page_size = page_size
        self.enabled = enabled

        self._stop = asyncio.Event()
        self._client: httpx.AsyncClient | None = None
        # Keep a small dedupe ring — the API may return overlapping pages.
        self._seen_ids: set[str] = set()
        self._seen_max: int = 5_000

        # Telemetry
        self.events_emitted: int = 0
        self.requests_made: int = 0
        self.last_poll_at: datetime | None = None
        self.last_error: str | None = None

    # MarketDataSource interface ------------------------------------------------

    async def start(self) -> None:
        token = os.environ.get("POLYMARKET_API_TOKEN")
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(base_url=self.api_base, headers=headers, timeout=20.0)

    async def stop(self) -> None:
        self._stop.set()
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def stream_events(self) -> AsyncIterator[MarketEvent]:
        if self._client is None:
            raise RuntimeError("call start() before stream_events()")

        while not self._stop.is_set():
            try:
                items = await self._fetch_recent()
                self.last_poll_at = datetime.now(tz=timezone.utc)
                for raw in items:
                    event = self._normalize(raw)
                    if event is None:
                        continue
                    yield event
                    self.events_emitted += 1
            except Exception as exc:  # noqa: BLE001
                self.last_error = repr(exc)
                logger.warning("[polymarket_activity] poll failed: %s", exc)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval_secs)
            except asyncio.TimeoutError:
                continue

    async def list_markets(self) -> Iterable[MarketMeta]:
        return []

    # Internal ------------------------------------------------------------------

    async def _fetch_recent(self) -> list[dict]:
        assert self._client is not None
        self.requests_made += 1
        # The activity endpoint name and params have shifted historically; this
        # helper tries the most-current path and returns an empty list on 404,
        # which lets the platform keep running while we update the path.
        for path in ("/activity", "/trades"):
            try:
                resp = await self._client.get(path, params={"limit": self.page_size})
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    items = data.get("activity") or data.get("trades") or data.get("data") or []
                else:
                    items = data
                return list(items) if isinstance(items, list) else []
            except httpx.HTTPError:
                continue
        return []

    def _normalize(self, raw: dict) -> MarketEvent | None:
        # Dedupe by activity id / tx hash
        ev_id = str(
            raw.get("id")
            or raw.get("transactionHash")
            or raw.get("hash")
            or raw.get("txHash")
            or ""
        )
        if not ev_id or ev_id in self._seen_ids:
            return None
        self._seen_ids.add(ev_id)
        if len(self._seen_ids) > self._seen_max:
            # Drop oldest by rebuilding the set with last-half (cheap, runs rarely)
            self._seen_ids = set(list(self._seen_ids)[self._seen_max // 2 :])

        kind = (raw.get("type") or raw.get("activityType") or "").lower()
        ts = _parse_ts(raw.get("timestamp") or raw.get("time") or raw.get("createdAt"))

        market_id = raw.get("market") or raw.get("conditionId") or raw.get("marketId")
        asset_id = raw.get("asset") or raw.get("tokenId") or raw.get("assetId")

        if "redemption" in kind or "redeem" in kind:
            event_type = EventType.ACTIVITY_REDEMPTION
        else:
            event_type = EventType.ACTIVITY_TRADE

        return MarketEvent.make(
            event_type=event_type,
            venue=VENUE,
            payload={
                "raw_id": ev_id,
                "wallet": raw.get("user") or raw.get("wallet") or raw.get("trader"),
                "side": raw.get("side"),
                "price": raw.get("price"),
                "size": raw.get("size") or raw.get("amount"),
                "usd_value": raw.get("usdValue") or raw.get("amountUsd"),
                "kind_raw": kind,
            },
            market_id=market_id,
            asset_id=asset_id,
            ts=ts,
        )


def _parse_ts(raw) -> datetime:
    if raw is None:
        return datetime.now(tz=timezone.utc)
    try:
        # Try ISO-8601
        if isinstance(raw, str) and "T" in raw:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        # Else integer / numeric epoch
        v = float(raw)
        # Heuristic: treat values bigger than 10^12 as ms
        if v > 1e12:
            return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc)
        return datetime.fromtimestamp(v, tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(tz=timezone.utc)


def plugin() -> PolymarketActivity:
    return PolymarketActivity()
