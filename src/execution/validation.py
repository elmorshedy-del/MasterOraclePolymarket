"""Fill validation pass + adverse-selection watcher.

Two background passes run periodically:

  1. **Tentative-fill validation** (5-minute window per DESIGN.md §4)
     For each fill marked tentative, query trades in the surrounding window.
     If our fill price was outside the actual trading range during the
     window, mark realism_flag=IMPLAUSIBLE so it's excluded from headline P&L.

  2. **Adverse selection watcher** (60-second post-fill check)
     For each maker fill, check the price 60s after fill. If it moved
     against us by ≥2¢, mark realism_flag=PICKED_OFF.

Both passes update existing rows; they do not create new fills. They are
strictly post-hoc tagging of fills that have already been recorded.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.db.connection import get_pool

logger = logging.getLogger(__name__)


PICKED_OFF_THRESHOLD = Decimal("0.02")
ADVERSE_LOOKAHEAD_SECS = 60
TENTATIVE_WINDOW_SECS = 300  # 5 minutes


class FillValidator:
    """Background process that runs both validation passes."""

    def __init__(self, run_interval_secs: float = 30.0) -> None:
        self.run_interval_secs = run_interval_secs
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

        self.runs_completed: int = 0
        self.implausible_marked: int = 0
        self.picked_off_marked: int = 0
        self.last_run_ts: datetime | None = None
        self.last_error: str | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="fill-validator")
        logger.info("fill validator started")

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
                await self._run_passes()
                self.runs_completed += 1
                self.last_run_ts = datetime.now(tz=UTC)
            except Exception as exc:
                self.last_error = repr(exc)
                logger.exception("fill validator run failed: %s", exc)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.run_interval_secs)
            except TimeoutError:
                continue

    async def _run_passes(self) -> None:
        try:
            pool = await get_pool()
        except RuntimeError:
            return  # No DB — skip silently

        await self._validate_tentative_fills(pool)
        await self._check_adverse_selection(pool)

    async def _validate_tentative_fills(self, pool) -> None:
        """Mark fills IMPLAUSIBLE if their price was outside trading range."""
        now = datetime.now(tz=UTC)
        window_end = now - timedelta(seconds=TENTATIVE_WINDOW_SECS)

        async with pool.acquire() as conn:
            # Pull fills that are old enough to validate but not yet validated
            rows = await conn.fetch(
                """
                SELECT fill_id, market_id, asset_id, side, price, ts_filled
                FROM paper_fills
                WHERE ts_filled <= $1
                  AND realism_flag = 'clean'
                  AND (metadata ? 'validated') = false
                LIMIT 500
                """,
                window_end,
            )

            for row in rows:
                window_start = row["ts_filled"] - timedelta(seconds=30)
                window_stop = row["ts_filled"] + timedelta(seconds=30)

                price_range = await conn.fetchrow(
                    """
                    SELECT
                        MIN((payload->>'price')::numeric) AS min_p,
                        MAX((payload->>'price')::numeric) AS max_p
                    FROM market_events
                    WHERE event_type = 'trade_print'
                      AND market_id = $1
                      AND asset_id = $2
                      AND ts >= $3 AND ts <= $4
                    """,
                    row["market_id"],
                    row["asset_id"],
                    window_start,
                    window_stop,
                )

                fill_price = row["price"]
                min_p = price_range["min_p"]
                max_p = price_range["max_p"]

                implausible = (
                    min_p is not None
                    and max_p is not None
                    and (fill_price < min_p - Decimal("0.005") or fill_price > max_p + Decimal("0.005"))
                )

                new_flag = "implausible" if implausible else "clean"
                await conn.execute(
                    """
                    UPDATE paper_fills
                    SET realism_flag = $1,
                        metadata = metadata || jsonb_build_object('validated', true)
                    WHERE fill_id = $2
                    """,
                    new_flag,
                    row["fill_id"],
                )
                if implausible:
                    self.implausible_marked += 1

    async def _check_adverse_selection(self, pool) -> None:
        """Tag maker fills PICKED_OFF if price moved adversely in 60s post-fill."""
        now = datetime.now(tz=UTC)
        eligible_max = now - timedelta(seconds=ADVERSE_LOOKAHEAD_SECS + 30)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT fill_id, market_id, asset_id, side, price, ts_filled, fill_type
                FROM paper_fills
                WHERE fill_type IN ('maker_fast', 'maker_slow')
                  AND ts_filled <= $1
                  AND realism_flag IN ('clean', 'thin_market')
                  AND (metadata ? 'adverse_checked') = false
                LIMIT 500
                """,
                eligible_max,
            )

            for row in rows:
                ahead_window_start = row["ts_filled"]
                ahead_window_end = row["ts_filled"] + timedelta(seconds=ADVERSE_LOOKAHEAD_SECS)

                # Look at trade prints in the 60s after fill
                prints = await conn.fetch(
                    """
                    SELECT (payload->>'price')::numeric AS price
                    FROM market_events
                    WHERE event_type = 'trade_print'
                      AND market_id = $1
                      AND asset_id = $2
                      AND ts > $3 AND ts <= $4
                    """,
                    row["market_id"],
                    row["asset_id"],
                    ahead_window_start,
                    ahead_window_end,
                )

                fill_price = row["price"]
                side = row["side"]
                picked_off = False
                for p in prints:
                    move = p["price"] - fill_price if side == "buy" else fill_price - p["price"]
                    # Adverse means price moved AGAINST our position direction
                    if side == "buy":
                        adverse_move = fill_price - p["price"]
                    else:
                        adverse_move = p["price"] - fill_price
                    if adverse_move >= PICKED_OFF_THRESHOLD:
                        picked_off = True
                        break

                new_flag = "picked_off" if picked_off else row.get("realism_flag", "clean")
                await conn.execute(
                    """
                    UPDATE paper_fills
                    SET realism_flag = $1,
                        metadata = metadata || jsonb_build_object('adverse_checked', true)
                    WHERE fill_id = $2
                    """,
                    new_flag,
                    row["fill_id"],
                )
                if picked_off:
                    self.picked_off_marked += 1
