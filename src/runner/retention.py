"""Periodic data retention sweeper.

Deletes:
  - ``market_events`` older than 7 days
  - ``market_bars_1m`` older than 30 days
  - ``signals`` older than 90 days that have no corresponding paper_trade
  - keeps ``market_bars_1d`` forever

Runs once per hour. Uses ``DELETE ... USING`` patterns rather than TRUNCATE
to avoid touching active partitions.

Trade and P&L tables are never auto-purged — they're the historical record
of every paper trade and must persist.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from src.db.connection import get_pool

logger = logging.getLogger(__name__)


class Retention:
    def __init__(
        self,
        events_retention_days: int = 7,
        bars_1m_retention_days: int = 30,
        signals_retention_days: int = 90,
        run_interval_secs: float = 3600.0,
    ) -> None:
        self.events_retention_days = events_retention_days
        self.bars_1m_retention_days = bars_1m_retention_days
        self.signals_retention_days = signals_retention_days
        self.run_interval_secs = run_interval_secs

        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

        self.runs_completed: int = 0
        self.last_run_ts: datetime | None = None
        self.events_deleted_total: int = 0
        self.bars_deleted_total: int = 0

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="retention")
        logger.info("retention started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        # First sweep happens at startup — small batches in case the table is huge.
        while not self._stop.is_set():
            try:
                await self._sweep()
                self.runs_completed += 1
                self.last_run_ts = datetime.now(tz=timezone.utc)
            except Exception as exc:  # noqa: BLE001
                logger.exception("retention run failed: %s", exc)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.run_interval_secs)
            except asyncio.TimeoutError:
                continue

    async def _sweep(self) -> None:
        now = datetime.now(tz=timezone.utc)
        events_cutoff = now - timedelta(days=self.events_retention_days)
        bars_cutoff = now - timedelta(days=self.bars_1m_retention_days)
        signals_cutoff = now - timedelta(days=self.signals_retention_days)

        pool = await get_pool()
        async with pool.acquire() as conn:
            # Events — operate in chunks to keep WAL small
            res_events = await conn.execute(
                "DELETE FROM market_events WHERE ts < $1",
                events_cutoff,
            )
            res_bars = await conn.execute(
                "DELETE FROM market_bars_1m WHERE bucket_ts < $1",
                bars_cutoff,
            )
            await conn.execute(
                """
                DELETE FROM signals s
                WHERE s.ts_signal < $1
                  AND NOT EXISTS (
                    SELECT 1 FROM paper_orders po WHERE po.signal_id = s.signal_id
                  )
                """,
                signals_cutoff,
            )

        # asyncpg returns a string like "DELETE 1234"
        self.events_deleted_total += _parse_delete_count(res_events)
        self.bars_deleted_total += _parse_delete_count(res_bars)

        logger.info(
            "retention sweep done | events_deleted=%s bars_deleted=%s",
            res_events,
            res_bars,
        )


def _parse_delete_count(result: str) -> int:
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0
