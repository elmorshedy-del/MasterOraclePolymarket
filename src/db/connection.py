"""Async Postgres connection pool.

Wraps asyncpg with sane defaults, retry/backoff, and a single global pool
shared across the worker, API, and periodic jobs. The pool is initialized
lazily on first call to ``get_pool()``.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import asyncpg
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


_pool: Optional[asyncpg.Pool] = None


def _normalize_url(url: str) -> str:
    """Convert SQLAlchemy-style ``postgresql+asyncpg://`` to plain ``postgresql://``."""
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


async def get_pool() -> asyncpg.Pool:
    """Return the process-global pool, initializing if needed."""
    global _pool
    if _pool is not None:
        return _pool

    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url:
        raise RuntimeError("DATABASE_URL not set")

    url = _normalize_url(raw_url)
    min_size = int(os.environ.get("DB_POOL_MIN", "2"))
    max_size = int(os.environ.get("DB_POOL_MAX", "10"))

    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type((OSError, asyncpg.PostgresConnectionError)),
        wait=wait_exponential(multiplier=0.5, max=10),
        stop=stop_after_attempt(8),
        reraise=True,
    ):
        with attempt:
            _pool = await asyncpg.create_pool(
                dsn=url,
                min_size=min_size,
                max_size=max_size,
                command_timeout=30,
                statement_cache_size=0,  # safer when schema migrates under us
            )
            logger.info("db pool ready (min=%d max=%d)", min_size, max_size)

    assert _pool is not None
    return _pool


async def close_pool() -> None:
    """Graceful pool shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("db pool closed")
