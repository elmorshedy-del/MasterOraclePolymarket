"""Binance USDT-margined perpetual ticker adapter.

Streams best bid/ask for a small set of perp pairs (default: BTCUSDT, ETHUSDT).
Used as the spot/perp anchor for ``stale_price_crypto`` and
``polymarket_vs_perp_basis`` strategies.

Public endpoint, no authentication required.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timezone

import orjson

from src.core.events import EventType, MarketEvent, MarketMeta
from src.core.interfaces import MarketDataSource
from src.venues._ws_helper import ReconnectingWS

logger = logging.getLogger(__name__)


VENUE = "binance_perp"
DEFAULT_WS_BASE = "wss://fstream.binance.com/stream"


class BinancePerp:
    name: str = "binance_perp"

    def __init__(
        self,
        symbols: Iterable[str] = ("btcusdt", "ethusdt"),
        enabled: bool = False,
    ) -> None:
        self.symbols = [s.lower() for s in symbols]
        self.enabled = enabled

        # Multi-stream URL — Binance lets us combine all bookTicker streams in one socket
        streams = "/".join(f"{s}@bookTicker" for s in self.symbols)
        self.ws_url = f"{DEFAULT_WS_BASE}?streams={streams}"

        self._ws: ReconnectingWS | None = None
        self._stop = asyncio.Event()

        self.events_emitted: int = 0
        self.last_event_at: datetime | None = None

    async def start(self) -> None:
        self._ws = ReconnectingWS(self.ws_url, name=self.name)

    async def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            self._ws.stop()

    async def stream_events(self) -> AsyncIterator[MarketEvent]:
        if self._ws is None:
            raise RuntimeError("call start() before stream_events()")

        async for raw in self._ws.stream():
            try:
                envelope = orjson.loads(raw)
            except orjson.JSONDecodeError:
                continue

            data = envelope.get("data", envelope)
            symbol = data.get("s")
            if not symbol:
                continue

            ts_ms = data.get("E") or data.get("T")
            ts = (
                datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
                if isinstance(ts_ms, (int, float))
                else datetime.now(tz=timezone.utc)
            )

            payload = {
                "symbol": symbol,
                "bid": data.get("b"),
                "bid_size": data.get("B"),
                "ask": data.get("a"),
                "ask_size": data.get("A"),
            }

            self.events_emitted += 1
            self.last_event_at = ts
            yield MarketEvent.make(
                event_type=EventType.EXTERNAL_PRICE,
                venue=VENUE,
                payload=payload,
                market_id=symbol,
                asset_id=symbol,
                ts=ts,
            )

    async def list_markets(self) -> Iterable[MarketMeta]:
        return []


def plugin() -> BinancePerp:
    return BinancePerp()
