"""Periodic P&L snapshotter — writes equity-curve points to ``sleeve_pnl_snapshots``.

Runs every minute. Reads current sleeve P&L from the in-memory
PositionTracker, computes unrealized P&L using the latest mid prices from
the OrderBookStore, and writes a snapshot row per sleeve.

The dashboard's per-sleeve equity curves are built from this table.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from src.db.connection import get_pool
from src.execution.position_tracker import PositionTracker
from src.venues._orderbook_store import STORE

logger = logging.getLogger(__name__)


class PnLSnapshotter:
    def __init__(
        self,
        position_tracker: PositionTracker,
        run_interval_secs: float = 60.0,
    ) -> None:
        self.position_tracker = position_tracker
        self.run_interval_secs = run_interval_secs

        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

        self.runs_completed: int = 0
        self.last_run_ts: datetime | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="pnl-snapshotter")
        logger.info("pnl snapshotter started")

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
                await self._snapshot_once()
                self.runs_completed += 1
                self.last_run_ts = datetime.now(tz=timezone.utc)
            except Exception as exc:  # noqa: BLE001
                logger.exception("pnl snapshot failed: %s", exc)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.run_interval_secs)
            except asyncio.TimeoutError:
                continue

    async def _snapshot_once(self) -> None:
        # Build mark prices from the in-memory book store
        mark_prices: dict[tuple[str, str], Decimal] = {}
        for (m, a) in STORE.known_keys():
            book = STORE.get(m, a)
            if book is None:
                continue
            mid = book.mid()
            if mid is not None:
                mark_prices[(m, a)] = mid

        try:
            pool = await get_pool()
        except RuntimeError:
            return

        now = datetime.now(tz=timezone.utc)
        rows: list[tuple] = []
        for sleeve_id in self.position_tracker.all_sleeve_ids():
            pnl = self.position_tracker.pnl(sleeve_id, mark_prices=mark_prices)
            rows.append((
                sleeve_id,
                now,
                pnl.realized,
                pnl.unrealized,
                pnl.capital_remaining + pnl.unrealized,
                pnl.open_position_count,
            ))

        if not rows:
            return

        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO sleeve_pnl_snapshots
                  (sleeve_id, ts, realized_pnl_usd, unrealized_pnl_usd, capital_remaining, open_positions)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (sleeve_id, ts) DO UPDATE SET
                  realized_pnl_usd = EXCLUDED.realized_pnl_usd,
                  unrealized_pnl_usd = EXCLUDED.unrealized_pnl_usd,
                  capital_remaining = EXCLUDED.capital_remaining,
                  open_positions = EXCLUDED.open_positions
                """,
                rows,
            )
