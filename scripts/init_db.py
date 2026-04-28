"""Apply src/db/schema.sql to the database referenced by DATABASE_URL.

Idempotent — uses CREATE TABLE IF NOT EXISTS throughout. Safe to re-run.

Usage:
    DATABASE_URL=postgresql://... python scripts/init_db.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg


async def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 1

    # asyncpg uses postgres://, not postgresql+asyncpg://
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)

    schema_path = Path(__file__).resolve().parents[1] / "src" / "db" / "schema.sql"
    if not schema_path.exists():
        print(f"ERROR: schema not found at {schema_path}", file=sys.stderr)
        return 1

    sql = schema_path.read_text()

    conn = await asyncpg.connect(url)
    try:
        await conn.execute(sql)
        print(f"Applied {schema_path} successfully.")
    finally:
        await conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
