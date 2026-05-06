"""Buffered, batched writer for ``market_events``.

The CLOB websocket can emit hundreds of events per second across all markets.
Writing each event individually overwhelms Postgres. The EventWriter buffers
events in-memory and flushes in batches.

Backpressure: if the buffer exceeds ``max_buffer``, the writer drops the
oldest events and increments a counter. We never block ingestion on writes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from contextlib import suppress

import orjson

from src.core.events import MarketEvent
from src.db.connection import get_pool

logger = logging.getLogger(__name__)


class EventWriter:
    def __init__(
        self,
        flush_interval_secs: float = 1.0,
        flush_batch_size: int = 500,
        max_buffer: int = 50_000,
    ) -> None:
        self.flush_interval_secs = flush_interval_secs
        self.flush_batch_size = flush_batch_size
        self.max_buffer = max_buffer

        self._buffer: deque[MarketEvent] = deque()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

        # Telemetry
        self.events_written: int = 0
        self.events_dropped: int = 0
        self.last_flush_ts: float = 0.0
        self.last_flush_count: int = 0

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._flush_loop(), name="event-writer-flush")
        logger.info("event writer started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        # Final flush
        await self._flush_once()
        logger.info("event writer stopped (written=%d dropped=%d)",
                    self.events_written, self.events_dropped)

    def submit(self, event: MarketEvent) -> None:
        if len(self._buffer) >= self.max_buffer:
            # Drop oldest
            self._buffer.popleft()
            self.events_dropped += 1
            if self.events_dropped % 1000 == 1:
                logger.warning("event buffer overflow; dropped=%d", self.events_dropped)
        self._buffer.append(event)

    async def _flush_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.flush_interval_secs)
            except TimeoutError:
                pass
            await self._flush_once()

    async def _flush_once(self) -> None:
        if not self._buffer:
            return

        batch: list[MarketEvent] = []
        while self._buffer and len(batch) < self.flush_batch_size:
            batch.append(self._buffer.popleft())

        if not batch:
            return

        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO market_events
                        (event_id, event_type, market_id, asset_id, venue, ts, payload)
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                    """,
                    [
                        (
                            ev.event_id,
                            ev.event_type.value,
                            ev.market_id,
                            ev.asset_id,
                            ev.venue,
                            ev.ts,
                            orjson.dumps(_serializable(ev.payload)).decode(),
                        )
                        for ev in batch
                    ],
                )
            self.events_written += len(batch)
            self.last_flush_count = len(batch)
            self.last_flush_ts = time.time()
        except Exception:
            logger.exception("event flush failed; %d events lost from this batch", len(batch))


def _serializable(payload: object) -> object:
    """orjson handles most things, but Decimals need str conversion."""
    from decimal import Decimal

    if isinstance(payload, Decimal):
        return str(payload)
    if isinstance(payload, dict):
        return {k: _serializable(v) for k, v in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [_serializable(x) for x in payload]
    return payload
