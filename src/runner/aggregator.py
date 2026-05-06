"""Periodic 1-minute bar aggregator.

Aggregates ``market_events`` (TRADE_PRINT and BOOK_SNAPSHOT/BOOK_DELTA close
prices) into ``market_bars_1m`` rows. Runs once per minute.

Why aggregate? Raw events are kept 7 days. 1-minute bars are kept 30 days.
Daily bars are kept forever. This keeps Postgres under ~5–8 GB steady state
even with 1000 active markets.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from src.db.connection import get_pool

logger = logging.getLogger(__name__)


_AGG_SQL = """
INSERT INTO market_bars_1m (
    market_id, asset_id, bucket_ts,
    open_price, high_price, low_price, close_price,
    volume, trade_count, bid_at_close, ask_at_close
)
SELECT
    market_id,
    asset_id,
    date_trunc('minute', ts) AS bucket_ts,
    (array_agg(price ORDER BY ts ASC))[1] AS open_price,
    MAX(price) AS high_price,
    MIN(price) AS low_price,
    (array_agg(price ORDER BY ts DESC))[1] AS close_price,
    SUM(size) AS volume,
    COUNT(*) AS trade_count,
    NULL::numeric AS bid_at_close,
    NULL::numeric AS ask_at_close
FROM (
    SELECT
        market_id,
        asset_id,
        ts,
        (payload->>'price')::numeric AS price,
        (payload->>'size')::numeric AS size
    FROM market_events
    WHERE event_type = 'trade_print'
      AND ts >= $1
      AND ts <  $2
      AND market_id IS NOT NULL
      AND asset_id IS NOT NULL
      AND payload ? 'price'
) sub
GROUP BY market_id, asset_id, date_trunc('minute', ts)
ON CONFLICT (market_id, asset_id, bucket_ts) DO UPDATE SET
    open_price  = EXCLUDED.open_price,
    high_price  = EXCLUDED.high_price,
    low_price   = EXCLUDED.low_price,
    close_price = EXCLUDED.close_price,
    volume      = EXCLUDED.volume,
    trade_count = EXCLUDED.trade_count;
"""


_DAILY_AGG_SQL = """
INSERT INTO market_bars_1d (
    market_id, asset_id, bucket_ts,
    open_price, high_price, low_price, close_price,
    volume, trade_count
)
SELECT
    market_id,
    asset_id,
    bucket_ts::date AS bucket_ts,
    (array_agg(open_price  ORDER BY bucket_ts ASC))[1] AS open_price,
    MAX(high_price) AS high_price,
    MIN(low_price)  AS low_price,
    (array_agg(close_price ORDER BY bucket_ts DESC))[1] AS close_price,
    SUM(volume) AS volume,
    SUM(trade_count) AS trade_count
FROM market_bars_1m
WHERE bucket_ts >= $1 AND bucket_ts < $2
GROUP BY market_id, asset_id, bucket_ts::date
ON CONFLICT (market_id, asset_id, bucket_ts) DO UPDATE SET
    open_price  = EXCLUDED.open_price,
    high_price  = EXCLUDED.high_price,
    low_price   = EXCLUDED.low_price,
    close_price = EXCLUDED.close_price,
    volume      = EXCLUDED.volume,
    trade_count = EXCLUDED.trade_count;
"""


class Aggregator:
    def __init__(self, run_interval_secs: float = 60.0) -> None:
        self.run_interval_secs = run_interval_secs
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

        self.runs_completed: int = 0
        self.last_run_ts: datetime | None = None
        self.last_error: str | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="aggregator")
        logger.info("aggregator started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._run_minute_aggregation()
                # Daily aggregation runs less often — every 10 minutes is plenty
                if self.runs_completed % 10 == 0:
                    await self._run_daily_aggregation()
                self.runs_completed += 1
                self.last_run_ts = datetime.now(tz=UTC)
            except Exception as exc:
                self.last_error = repr(exc)
                logger.exception("aggregator run failed: %s", exc)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.run_interval_secs)
            except TimeoutError:
                continue

    async def _run_minute_aggregation(self) -> None:
        # Aggregate the most recent fully-closed minute
        now = datetime.now(tz=UTC)
        end = now.replace(second=0, microsecond=0)
        start = end - timedelta(minutes=2)

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(_AGG_SQL, start, end)

    async def _run_daily_aggregation(self) -> None:
        now = datetime.now(tz=UTC)
        # Aggregate yesterday + today's partial day
        start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(_DAILY_AGG_SQL, start, end)
