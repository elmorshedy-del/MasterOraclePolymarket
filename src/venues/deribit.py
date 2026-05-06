"""Deribit options/futures public websocket adapter.

Subscribes to ticker and book channels for BTC and ETH instruments. Emits
EXTERNAL_PRICE events tagged with the instrument name so crypto-IV-arb
strategies can join them with Polymarket binary-option markets.

We don't reconstruct a full orderbook for Deribit (it's not where we trade
in V1). We pull tickers (best bid/ask/index price) at low frequency.

API: https://docs.deribit.com/#ws-public-channels
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
from decimal import Decimal

import orjson

from src.core.events import EventType, MarketEvent, MarketMeta
from src.venues._ws_helper import ReconnectingWS, safe_send

logger = logging.getLogger(__name__)


VENUE = "deribit"
DEFAULT_WS_URL = "wss://www.deribit.com/ws/api/v2/"


class Deribit:
    name: str = "deribit"

    def __init__(
        self,
        ws_url: str | None = None,
        instruments: Iterable[str] = (
            "BTC-PERPETUAL",
            "ETH-PERPETUAL",
        ),
        enabled: bool = False,
    ) -> None:
        self.ws_url = ws_url or os.environ.get("DERIBIT_WS_URL", DEFAULT_WS_URL)
        self.instruments = list(instruments)
        self.enabled = enabled

        self._ws: ReconnectingWS | None = None
        self._stop = asyncio.Event()
        self._req_id = itertools.count(1)

        self.events_emitted: int = 0
        self.last_event_at: datetime | None = None

    async def start(self) -> None:
        async def _setup(ws):
            channels = [f"ticker.{inst}.raw" for inst in self.instruments]
            sub_msg = {
                "jsonrpc": "2.0",
                "id": next(self._req_id),
                "method": "public/subscribe",
                "params": {"channels": channels},
            }
            await safe_send(ws, sub_msg)
            logger.info("[deribit] subscribed to %d channels", len(channels))

        self._ws = ReconnectingWS(self.ws_url, name=self.name, setup=_setup)

    async def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            self._ws.stop()

    async def stream_events(self) -> AsyncIterator[MarketEvent]:
        if self._ws is None:
            raise RuntimeError("call start() before stream_events()")

        async for raw in self._ws.stream():
            try:
                msg = orjson.loads(raw)
            except orjson.JSONDecodeError:
                continue

            params = msg.get("params") or {}
            channel = params.get("channel", "")
            if not channel.startswith("ticker."):
                continue

            data = params.get("data") or {}
            instrument = data.get("instrument_name")
            if not instrument:
                continue

            ts_ms = data.get("timestamp")
            ts = (
                datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC)
                if isinstance(ts_ms, (int, float))
                else datetime.now(tz=UTC)
            )

            payload = {
                "instrument": instrument,
                "best_bid_price": _to_str(data.get("best_bid_price")),
                "best_ask_price": _to_str(data.get("best_ask_price")),
                "mark_price": _to_str(data.get("mark_price")),
                "index_price": _to_str(data.get("index_price")),
                "open_interest": data.get("open_interest"),
                "mark_iv": data.get("mark_iv"),
                "underlying_index": data.get("underlying_index"),
                "underlying_price": _to_str(data.get("underlying_price")),
            }

            self.events_emitted += 1
            self.last_event_at = ts
            yield MarketEvent.make(
                event_type=EventType.EXTERNAL_PRICE,
                venue=VENUE,
                payload=payload,
                market_id=instrument,
                asset_id=instrument,
                ts=ts,
            )

    async def list_markets(self) -> Iterable[MarketMeta]:
        return []


def _to_str(v) -> str | None:
    if v is None:
        return None
    try:
        return str(Decimal(str(v)))
    except Exception:
        return None


def plugin() -> Deribit:
    return Deribit()
