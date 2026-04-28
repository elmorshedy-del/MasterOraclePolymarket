"""Reconnecting websocket helper.

Wraps ``websockets`` with exponential backoff, a per-connection setup hook
(for subscription messages), and a clean shutdown signal. All venue
adapters that use websockets share this.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)


SetupFn = Callable[[WebSocketClientProtocol], Awaitable[None]]


class ReconnectingWS:
    """Yields parsed (raw text) messages from a websocket; reconnects on drop.

    Caller does its own message parsing — this class is venue-agnostic.
    """

    def __init__(
        self,
        url: str,
        name: str,
        setup: SetupFn | None = None,
        ping_interval: float = 20.0,
        ping_timeout: float = 20.0,
        backoff_initial: float = 1.0,
        backoff_max: float = 60.0,
    ) -> None:
        self.url = url
        self.name = name
        self.setup = setup
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.backoff_initial = backoff_initial
        self.backoff_max = backoff_max

        self._stop = asyncio.Event()

        # Telemetry
        self.connections_attempted: int = 0
        self.connections_successful: int = 0
        self.last_message_at: float | None = None
        self.last_error: str | None = None

    def stop(self) -> None:
        self._stop.set()

    async def stream(self) -> AsyncIterator[str]:
        backoff = self.backoff_initial
        loop = asyncio.get_running_loop()

        while not self._stop.is_set():
            self.connections_attempted += 1
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    max_size=2**22,  # 4 MiB — orderbook snapshots can be big
                ) as ws:
                    self.connections_successful += 1
                    backoff = self.backoff_initial
                    logger.info("[%s] ws connected", self.name)

                    if self.setup is not None:
                        await self.setup(ws)

                    async for raw in ws:
                        self.last_message_at = loop.time()
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", errors="replace")
                        yield raw
                        if self._stop.is_set():
                            break
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.last_error = repr(exc)
                logger.warning("[%s] ws error: %s — reconnecting in %.1fs", self.name, exc, backoff)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                    break  # stop requested during backoff
                except asyncio.TimeoutError:
                    backoff = min(backoff * 2, self.backoff_max)
            else:
                # Clean close (no exception) — reconnect quickly unless stopping
                if not self._stop.is_set():
                    logger.info("[%s] ws closed cleanly — reconnecting", self.name)
                    await asyncio.sleep(self.backoff_initial)


async def safe_send(ws: WebSocketClientProtocol, message: dict[str, Any]) -> None:
    """Convenience: orjson-serialize a dict and send."""
    import orjson

    await ws.send(orjson.dumps(message).decode("utf-8"))
