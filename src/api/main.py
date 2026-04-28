"""FastAPI surface for the dashboard.

Phase 1 endpoints:
  - GET /health                       — basic liveness
  - GET /version
  - GET /system/health                — pipe status, DB lag, event counts
  - GET /system/markets/count         — count of markets known
  - GET /system/orderbooks/count      — orderbooks held in memory

Phase 3 will add:
  - sleeves, equity curves, trades, pivots, replay
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.db.connection import get_pool
from src.venues._orderbook_store import STORE

app = FastAPI(title="Master Paper Trade Lab API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
async def version() -> dict[str, str]:
    return {"version": "0.1.0", "phase": "1"}


@app.get("/system/health")
async def system_health() -> dict[str, object]:
    """Aggregated platform health for the dashboard sidebar."""
    db_status = "unknown"
    db_now: str | None = None
    event_count_recent: int | None = None
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT now() AS now")
            db_now = row["now"].isoformat() if row else None
            db_status = "ok"
            count_row = await conn.fetchrow(
                "SELECT count(*) AS c FROM market_events WHERE ts > now() - interval '5 minutes'"
            )
            event_count_recent = int(count_row["c"]) if count_row else 0
    except Exception as exc:  # noqa: BLE001
        db_status = f"error: {exc!s}"

    return {
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "db": {
            "status": db_status,
            "server_time": db_now,
            "events_last_5min": event_count_recent,
        },
        "orderbooks": {
            "markets_in_memory": STORE.market_count(),
            "asset_books_in_memory": STORE.asset_count(),
            "snapshots_applied_total": STORE.snapshots_applied,
            "deltas_applied_total": STORE.deltas_applied,
        },
    }


@app.get("/system/markets/count")
async def markets_count() -> dict[str, int]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT count(*) AS c FROM markets")
            return {"count": int(row["c"]) if row else 0}
    except Exception:  # noqa: BLE001
        return {"count": 0}


@app.get("/system/orderbooks/sample")
async def orderbooks_sample(limit: int = 10) -> dict[str, list[dict[str, object]]]:
    """Return a small sample of in-memory orderbooks for debugging."""
    sample: list[dict[str, object]] = []
    for (market_id, asset_id) in STORE.known_keys()[:limit]:
        book = STORE.get(market_id, asset_id)
        if book is None:
            continue
        bid = book.best_bid()
        ask = book.best_ask()
        sample.append({
            "market_id": market_id,
            "asset_id": asset_id,
            "best_bid": str(bid.price) if bid else None,
            "best_ask": str(ask.price) if ask else None,
            "mid": str(book.mid()) if book.mid() is not None else None,
            "last_update": book.last_update_ts.isoformat() if book.last_update_ts else None,
        })
    return {"books": sample}
