"""Apply src/db/schema.sql idempotently. Safe to run on every boot.

Reads DATABASE_URL from env and runs the schema as one transaction. Every
table uses CREATE TABLE IF NOT EXISTS, so re-runs are no-ops.

Run modes:
  python -m scripts.bootstrap_db                       # apply schema, exit
  python -m scripts.bootstrap_db --wait                # wait for DB then apply
  python -m scripts.bootstrap_db --check               # exit 0 if connectable
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

import asyncpg

logger = logging.getLogger("bootstrap_db")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "src" / "db" / "schema.sql"


def _normalize_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


async def _connect(url: str) -> asyncpg.Connection:
    return await asyncpg.connect(url, command_timeout=30)


async def apply_schema(url: str) -> None:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"schema not found at {SCHEMA_PATH}")
    sql = SCHEMA_PATH.read_text()
    conn = await _connect(url)
    try:
        async with conn.transaction():
            await conn.execute(sql)
        logger.info("schema applied (idempotent) — %d bytes", len(sql))
    finally:
        await conn.close()


async def wait_for_db(url: str, timeout_secs: int = 120) -> None:
    """Poll until DB accepts a connection, up to timeout_secs."""
    deadline = time.time() + timeout_secs
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            conn = await _connect(url)
            await conn.execute("SELECT 1")
            await conn.close()
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.info("DB not ready yet: %s — retrying", exc)
            await asyncio.sleep(2)
    raise TimeoutError(f"DB unreachable after {timeout_secs}s; last={last_err!r}")


async def check(url: str) -> int:
    try:
        conn = await _connect(url)
        await conn.execute("SELECT 1")
        await conn.close()
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("check failed: %s", exc)
        return 1


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", action="store_true",
                    help="wait for DB up to 120s before applying schema")
    ap.add_argument("--check", action="store_true",
                    help="exit 0 if DB connectable, else 1")
    args = ap.parse_args()

    raw = os.environ.get("DATABASE_URL")
    if not raw:
        logger.error("DATABASE_URL not set")
        return 2
    url = _normalize_url(raw)

    if args.check:
        return await check(url)

    if args.wait:
        await wait_for_db(url, timeout_secs=int(os.environ.get("DB_WAIT_SECS", "120")))

    await apply_schema(url)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
