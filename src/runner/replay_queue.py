"""Background replay job queue.

The API submits replay jobs (POST /replay/run); a single worker task pops
them and runs them through ReplayEngine. Status flows: queued → running →
completed / failed. Results land in ``replay_runs`` (header + summary) and
``paper_trades`` (tagged source='replay').

V1 is single-worker, in-memory. The queue resets if the process restarts
(running jobs get marked 'failed' on next boot).
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from src.runner.replay_engine import ReplayEngine, ReplayOverrides, ReplayResult

logger = logging.getLogger(__name__)


@dataclass
class ReplayJob:
    job_id: UUID
    strategy_name: str
    config_id: str = "default"
    sleeve_id: str | None = None
    range_start: datetime | None = None
    range_end: datetime | None = None
    starting_capital: Decimal = Decimal("5000")
    edge_class: str | None = None
    overrides: ReplayOverrides = field(default_factory=ReplayOverrides)
    submitted_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    status: str = "queued"        # queued | running | completed | failed
    result: ReplayResult | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ReplayQueue:
    def __init__(self) -> None:
        self._engine = ReplayEngine()
        self._queue: deque[ReplayJob] = deque()
        self._jobs: dict[UUID, ReplayJob] = {}
        self._notify = asyncio.Event()
        self._stop = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._worker is not None:
            return
        self._stop.clear()
        self._worker = asyncio.create_task(self._loop(), name="replay-queue-worker")
        logger.info("replay queue worker started")

    async def stop(self) -> None:
        self._stop.set()
        self._notify.set()
        if self._worker is not None:
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    def submit(self, job: ReplayJob) -> ReplayJob:
        if job.job_id in self._jobs:
            return self._jobs[job.job_id]
        self._jobs[job.job_id] = job
        self._queue.append(job)
        self._notify.set()
        return job

    def get(self, job_id: UUID) -> ReplayJob | None:
        return self._jobs.get(job_id)

    def list(self, limit: int = 50) -> list[ReplayJob]:
        return list(self._jobs.values())[-limit:][::-1]

    async def _loop(self) -> None:
        while not self._stop.is_set():
            if not self._queue:
                self._notify.clear()
                try:
                    await asyncio.wait_for(self._notify.wait(), timeout=5.0)
                except TimeoutError:
                    pass
                continue

            job = self._queue.popleft()
            job.status = "running"
            job.started_at = datetime.now(tz=UTC)

            try:
                result = await self._engine.run(
                    strategy_name=job.strategy_name,
                    config_id=job.config_id,
                    sleeve_id=job.sleeve_id,
                    range_start=job.range_start,
                    range_end=job.range_end,
                    starting_capital=job.starting_capital,
                    edge_class=job.edge_class,
                    overrides=job.overrides,
                )
                job.result = result
                job.status = "completed"
            except Exception as exc:
                logger.exception("replay job %s failed", job.job_id)
                job.error = repr(exc)
                job.status = "failed"
            finally:
                job.finished_at = datetime.now(tz=UTC)


_queue_singleton: ReplayQueue | None = None


def get_queue() -> ReplayQueue:
    global _queue_singleton
    if _queue_singleton is None:
        _queue_singleton = ReplayQueue()
    return _queue_singleton
