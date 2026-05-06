"""Polymarket CLOB websocket adapter.

Subscribes to the public market channel for a configured set of asset_ids.
Reconstructs the in-memory order book from the event stream and emits
normalized ``MarketEvent`` instances.

Polymarket CLOB websocket schema (the relevant message types):

  - ``book`` — full snapshot. Fields:
        ``asset_id``, ``market``, ``timestamp``, ``hash``,
        ``bids``: [{"price": "0.50", "size": "100"}, ...],
        ``asks``: [{"price": "0.52", "size": "150"}, ...]

  - ``price_change`` — incremental update. Fields:
        ``asset_id``, ``market``, ``timestamp``,
        ``changes``: [{"price": "0.50", "side": "BUY", "size": "0"}]
        size is the NEW absolute size at that price (0 = remove).

  - ``last_trade_price`` — public trade. Fields:
        ``asset_id``, ``market``, ``timestamp``,
        ``price``, ``size``, ``side`` ("BUY" | "SELL"), ``fee_rate_bps``

  - ``tick_size_change`` — tick size update.

Source: https://docs.polymarket.com/#websocket-api
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
from decimal import Decimal

import orjson

from src.core.events import EventType, MarketEvent, MarketMeta, Side
from src.venues._orderbook_store import STORE
from src.venues._ws_helper import ReconnectingWS, safe_send

logger = logging.getLogger(__name__)


VENUE = "polymarket"
DEFAULT_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
SUBSCRIBE_BATCH_SIZE = 100  # Polymarket caps assets per subscribe message


class PolymarketCLOB:
    name: str = "polymarket_clob"

    def __init__(
        self,
        ws_url: str | None = None,
        asset_ids: Iterable[str] = (),
        enabled: bool = True,
    ) -> None:
        self.ws_url = ws_url or os.environ.get("POLYMARKET_CLOB_WS_URL", DEFAULT_WS_URL)
        self._asset_ids: list[str] = list(asset_ids)
        self.enabled = enabled

        self._ws: ReconnectingWS | None = None
        self._stop = asyncio.Event()

        # Telemetry
        self.events_emitted: int = 0
        self.last_event_at: datetime | None = None
        self.subscribed_assets: int = 0

    # -----------------------------------------------------------------------
    # Public mutators
    # -----------------------------------------------------------------------

    def set_asset_ids(self, asset_ids: Iterable[str]) -> None:
        """Replace the subscription set in place. Call ``resubscribe()`` to
        push the new list to Polymarket (drops + re-establishes the WS so
        the setup hook re-runs with the new list)."""
        self._asset_ids = list(asset_ids)

    async def resubscribe(self) -> None:
        """Force a reconnect so the new asset_ids list is applied.

        Polymarket's CLOB WS does not document a reliable in-band unsubscribe
        path; reconnecting is the cleanest way to mutate the subscription
        set. Cheap (sub-second on a working link) and safe — the in-memory
        order book repopulates from the post-reconnect BOOK snapshots.
        """
        if self._ws is not None:
            await self._ws.cycle()

    # -----------------------------------------------------------------------
    # MarketDataSource interface
    # -----------------------------------------------------------------------

    async def start(self) -> None:
        async def _setup(ws):
            # Polymarket subscribe message — batched if list is large.
            for chunk in _chunks(self._asset_ids, SUBSCRIBE_BATCH_SIZE):
                await safe_send(ws, {"type": "MARKET", "assets_ids": chunk})
            self.subscribed_assets = len(self._asset_ids)
            logger.info("[polymarket_clob] subscribed to %d assets", self.subscribed_assets)

        self._ws = ReconnectingWS(
            url=self.ws_url,
            name=self.name,
            setup=_setup,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            self._ws.stop()

    async def stream_events(self) -> AsyncIterator[MarketEvent]:
        if self._ws is None:
            raise RuntimeError("call start() before stream_events()")

        async for raw in self._ws.stream():
            try:
                data = orjson.loads(raw)
            except orjson.JSONDecodeError:
                logger.warning("[polymarket_clob] non-JSON message: %r", raw[:200])
                continue

            # Polymarket sometimes sends arrays of events
            payloads = data if isinstance(data, list) else [data]
            for msg in payloads:
                event = _normalize(msg)
                if event is None:
                    continue
                self.events_emitted += 1
                self.last_event_at = event.ts
                yield event

    async def list_markets(self) -> Iterable[MarketMeta]:
        # The CLOB websocket does not enumerate markets; that comes from the
        # data API. Phase 1 leaves this empty; the rest_poller adapter
        # populates it.
        return []


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _normalize(msg: dict) -> MarketEvent | None:
    """Translate a Polymarket WS message into a MarketEvent, also updating STORE."""
    event_type = msg.get("event_type") or msg.get("type")
    if event_type is None:
        return None

    asset_id = msg.get("asset_id")
    market = msg.get("market") or msg.get("market_id")
    ts_raw = msg.get("timestamp")
    ts = _parse_ts(ts_raw)

    if event_type == "book":
        bids = [(Decimal(b["price"]), Decimal(b["size"])) for b in msg.get("bids", [])]
        asks = [(Decimal(a["price"]), Decimal(a["size"])) for a in msg.get("asks", [])]
        if market and asset_id:
            STORE.apply_snapshot(market, asset_id, bids, asks, ts)
        return MarketEvent.make(
            event_type=EventType.BOOK_SNAPSHOT,
            venue=VENUE,
            payload={
                "bids": [{"price": str(p), "size": str(s)} for p, s in bids],
                "asks": [{"price": str(p), "size": str(s)} for p, s in asks],
                "hash": msg.get("hash"),
            },
            market_id=market,
            asset_id=asset_id,
            ts=ts,
        )

    if event_type == "price_change":
        changes = msg.get("changes") or []
        normalized_changes: list[dict] = []
        for ch in changes:
            try:
                side = Side.BUY if ch.get("side", "").upper() == "BUY" else Side.SELL
                price = Decimal(ch["price"])
                size = Decimal(ch["size"])
            except (KeyError, ValueError):
                continue
            if market and asset_id:
                STORE.apply_delta(market, asset_id, side, price, size, ts)
            normalized_changes.append({
                "side": side.value,
                "price": str(price),
                "size": str(size),
            })
        return MarketEvent.make(
            event_type=EventType.BOOK_DELTA,
            venue=VENUE,
            payload={"changes": normalized_changes},
            market_id=market,
            asset_id=asset_id,
            ts=ts,
        )

    if event_type == "last_trade_price":
        try:
            price = Decimal(str(msg.get("price")))
            size = Decimal(str(msg.get("size")))
        except (TypeError, ValueError):
            return None
        side = Side.BUY if str(msg.get("side", "")).upper() == "BUY" else Side.SELL
        return MarketEvent.make(
            event_type=EventType.TRADE_PRINT,
            venue=VENUE,
            payload={
                "price": str(price),
                "size": str(size),
                "side": side.value,
                "fee_rate_bps": msg.get("fee_rate_bps"),
            },
            market_id=market,
            asset_id=asset_id,
            ts=ts,
        )

    if event_type == "tick_size_change":
        return MarketEvent.make(
            event_type=EventType.TICK_SIZE_CHANGE,
            venue=VENUE,
            payload={
                "old_tick_size": msg.get("old_tick_size"),
                "new_tick_size": msg.get("new_tick_size"),
            },
            market_id=market,
            asset_id=asset_id,
            ts=ts,
        )

    return None


def _parse_ts(raw) -> datetime:
    """Polymarket timestamps come as ms-since-epoch strings or ints."""
    if raw is None:
        return datetime.now(tz=UTC)
    try:
        ms = int(raw)
        return datetime.fromtimestamp(ms / 1000.0, tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(tz=UTC)


def _chunks(seq: list[str], n: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


# ---------------------------------------------------------------------------
# Plugin factory
# ---------------------------------------------------------------------------


def plugin() -> PolymarketCLOB:
    return PolymarketCLOB()
