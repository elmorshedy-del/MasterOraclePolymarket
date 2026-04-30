"""Polymarket markets metadata poller.

Polls the data-api for the active markets list, refreshes ``markets`` table,
and provides the asset_id list that the CLOB websocket subscribes to.

This is not a streaming source — it's a periodic REST poller. It still
implements ``MarketDataSource`` because (a) we want it in the auto-discovery
list and (b) market resolutions arrive here as ``MARKET_RESOLVED`` events.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from src.core.events import EventType, MarketEvent, MarketMeta
from src.core.interfaces import MarketDataSource

logger = logging.getLogger(__name__)


VENUE = "polymarket"
DEFAULT_API_BASE = "https://data-api.polymarket.com"


class PolymarketMarkets:
    name: str = "polymarket_markets"

    def __init__(
        self,
        api_base: str | None = None,
        poll_interval_secs: float = 300.0,
        top_n: int = 1000,
        enabled: bool = True,
    ) -> None:
        self.api_base = api_base or os.environ.get("POLYMARKET_DATA_API_URL", DEFAULT_API_BASE)
        self.poll_interval_secs = poll_interval_secs
        self.top_n = top_n
        self.enabled = enabled

        self._stop = asyncio.Event()
        self._client: httpx.AsyncClient | None = None
        self._known_meta: dict[str, MarketMeta] = {}
        self._last_resolution_state: dict[str, bool] = {}

        self.requests_made: int = 0
        self.markets_known: int = 0
        self.last_poll_at: datetime | None = None
        self.last_error: str | None = None

    async def start(self) -> None:
        token = os.environ.get("POLYMARKET_API_TOKEN")
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(base_url=self.api_base, headers=headers, timeout=30.0)

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
                markets = await self._fetch_markets()
                self.last_poll_at = datetime.now(tz=timezone.utc)
                for meta in markets:
                    is_new = meta.market_id not in self._known_meta
                    self._known_meta[meta.market_id] = meta

                    # Emit MARKET_META on first observation so strategies can
                    # cache category / end_time / volume_24h / asset_ids.
                    if is_new:
                        for asset_id in meta.asset_ids:
                            yield MarketEvent.make(
                                event_type=EventType.MARKET_META,
                                venue=VENUE,
                                payload={
                                    "title": meta.title,
                                    "category": meta.category,
                                    "subcategory": meta.subcategory,
                                    "end_time": meta.end_time.isoformat() if meta.end_time else None,
                                    "tick_size": str(meta.tick_size),
                                    "asset_ids": list(meta.asset_ids),
                                    "tags_extra": meta.tags_extra,
                                },
                                market_id=meta.market_id,
                                asset_id=asset_id,
                                ts=datetime.now(tz=timezone.utc),
                            )

                    # Resolution detection — fire MARKET_RESOLVED once
                    is_resolved = bool(meta.tags_extra.get("resolved"))
                    prev = self._last_resolution_state.get(meta.market_id, False)
                    if is_resolved and not prev:
                        yield MarketEvent.make(
                            event_type=EventType.MARKET_RESOLVED,
                            venue=VENUE,
                            payload={
                                "title": meta.title,
                                "category": meta.category,
                                "resolution": meta.tags_extra.get("resolution"),
                            },
                            market_id=meta.market_id,
                            ts=datetime.now(tz=timezone.utc),
                        )
                    self._last_resolution_state[meta.market_id] = is_resolved

                self.markets_known = len(self._known_meta)
                logger.info("[polymarket_markets] tracking %d markets", self.markets_known)
            except Exception as exc:  # noqa: BLE001
                self.last_error = repr(exc)
                logger.warning("[polymarket_markets] poll failed: %s", exc)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval_secs)
            except asyncio.TimeoutError:
                continue

    async def list_markets(self) -> Iterable[MarketMeta]:
        return list(self._known_meta.values())

    # Convenience: list of asset_ids for the CLOB to subscribe to.
    def asset_ids(self) -> list[str]:
        ids: list[str] = []
        for m in self._known_meta.values():
            ids.extend(m.asset_ids)
        return ids

    # --------------------------------------------------------------------------

    async def _fetch_markets(self) -> list[MarketMeta]:
        assert self._client is not None
        self.requests_made += 1

        # The data API exposes /markets; fall back gracefully if it shifts.
        for path in ("/markets", "/v1/markets"):
            try:
                resp = await self._client.get(
                    path,
                    params={"limit": self.top_n, "active": "true"},
                )
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    raw_list = data.get("markets") or data.get("data") or []
                else:
                    raw_list = data
                return [m for m in (_parse_market(r) for r in raw_list) if m is not None]
            except httpx.HTTPError:
                continue
        return []


def _parse_market(raw: dict) -> MarketMeta | None:
    try:
        market_id = (
            raw.get("conditionId")
            or raw.get("condition_id")
            or raw.get("id")
            or raw.get("slug")
        )
        if not market_id:
            return None

        # Asset ids — Polymarket markets often have a ``tokens`` array with token_id
        asset_ids: list[str] = []
        for token in raw.get("tokens", []):
            tid = token.get("token_id") or token.get("id")
            if tid:
                asset_ids.append(str(tid))
        if not asset_ids:
            # Fallback for older shapes
            tid = raw.get("tokenId") or raw.get("yesTokenId")
            if tid:
                asset_ids.append(str(tid))

        end_time = None
        end_raw = raw.get("end_date_iso") or raw.get("endDate") or raw.get("end_date")
        if isinstance(end_raw, str) and end_raw:
            try:
                end_time = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
            except ValueError:
                pass

        tick_size_raw = raw.get("minimum_tick_size") or raw.get("tickSize") or "0.01"
        try:
            tick_size = Decimal(str(tick_size_raw))
        except Exception:  # noqa: BLE001
            tick_size = Decimal("0.01")

        category = raw.get("category") or raw.get("topCategory") or "uncategorized"

        return MarketMeta(
            market_id=str(market_id),
            venue="polymarket",
            venue_market_id=str(raw.get("slug") or market_id),
            asset_ids=tuple(asset_ids),
            title=str(raw.get("question") or raw.get("title") or ""),
            category=str(category).lower(),
            subcategory=raw.get("subcategory"),
            end_time=end_time,
            tick_size=tick_size,
            tags_extra={
                "resolved": bool(raw.get("closed") or raw.get("resolved")),
                "resolution": raw.get("resolution"),
                "volume_24h": raw.get("volume24hr") or raw.get("volume_24h"),
                "volume_total": raw.get("volume"),
                "liquidity": raw.get("liquidity"),
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("failed to parse market: %s", raw.get("id") if isinstance(raw, dict) else "?")
        return None


def plugin() -> PolymarketMarkets:
    return PolymarketMarkets()
