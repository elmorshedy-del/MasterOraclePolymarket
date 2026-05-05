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

    async def _on_connect(conn: asyncpg.Connection) -> None:
        """Register Decimal codec for Postgres NUMERIC.

        Audit Low-4: writers were going Decimal → str(float()) → DB and back.
        Float intermediation introduces silent precision loss on prices like
        '0.4895' → 0.4894999... With this codec, asyncpg accepts Decimal
        directly and round-trips it as Decimal. Money columns stay precise
        end-to-end.
        """
        from decimal import Decimal as _D
        await conn.set_type_codec(
            "numeric",
            encoder=lambda v: str(v) if isinstance(v, _D) else str(_D(str(v))),
            decoder=lambda s: _D(s),
            schema="pg_catalog",
            format="text",
        )

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
                init=_on_connect,
            )
            logger.info("db pool ready (min=%d max=%d) with Decimal codec", min_size, max_size)

    assert _pool is not None
    return _pool


async def close_pool() -> None:
    """Graceful pool shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("db pool closed")
