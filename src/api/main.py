"""FastAPI surface for the dashboard.

Phase 2 endpoints:
  - GET /health
  - GET /version
  - GET /system/health
  - GET /system/markets/count
  - GET /system/orderbooks/sample
  - GET /system/sleeves         — list all configured sleeves with mode + capital
  - GET /system/positions       — open positions across sleeves
  - GET /system/recent_fills    — last N paper fills
  - GET /system/recent_trades   — last N paper trades
  - GET /system/sleeve_pnl      — equity-curve points for one or all sleeves
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from src.db.connection import get_pool
from src.venues._orderbook_store import STORE

app = FastAPI(title="Master Paper Trade Lab API", version="0.2.0")

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
    return {"version": "0.2.0", "phase": "2"}


@app.get("/system/health")
async def system_health() -> dict[str, object]:
    db_status = "unknown"
    db_now: str | None = None
    event_count_recent: int | None = None
    fills_recent: int | None = None
    trades_recent: int | None = None
    open_positions: int | None = None
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT now() AS now")
            db_now = row["now"].isoformat() if row else None
            db_status = "ok"
            event_count_recent = await conn.fetchval(
                "SELECT count(*) FROM market_events WHERE ts > now() - interval '5 minutes'"
            )
            fills_recent = await conn.fetchval(
                "SELECT count(*) FROM paper_fills WHERE ts_filled > now() - interval '1 hour'"
            )
            trades_recent = await conn.fetchval(
                "SELECT count(*) FROM paper_trades WHERE entry_ts > now() - interval '1 hour'"
            )
            open_positions = await conn.fetchval(
                "SELECT count(*) FROM paper_positions WHERE size > 0"
            )
    except Exception as exc:  # noqa: BLE001
        db_status = f"error: {exc!s}"

    return {
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "db": {
            "status": db_status,
            "server_time": db_now,
            "events_last_5min": event_count_recent,
            "fills_last_1h": fills_recent,
            "trades_last_1h": trades_recent,
            "open_positions": open_positions,
        },
        "orderbooks": {
            "markets_in_memory": STORE.market_count(),
            "asset_books_in_memory": STORE.asset_count(),
            "snapshots_applied_total": STORE.snapshots_applied,
            "deltas_applied_total": STORE.deltas_applied,
        },
    }


@app.get("/system/sleeves")
async def list_sleeves() -> dict[str, list[dict[str, Any]]]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.sleeve_id, s.strategy_name, s.config_id, s.edge_class,
                       s.starting_capital_usd, s.mode, s.enabled, s.config_hash,
                       s.started_at,
                       COALESCE(p.realized_pnl_usd, 0) AS realized_pnl_usd,
                       COALESCE(p.unrealized_pnl_usd, 0) AS unrealized_pnl_usd,
                       COALESCE(p.capital_remaining, s.starting_capital_usd) AS capital_remaining,
                       COALESCE(p.open_positions, 0) AS open_positions
                FROM sleeves s
                LEFT JOIN LATERAL (
                    SELECT * FROM sleeve_pnl_snapshots
                    WHERE sleeve_id = s.sleeve_id
                    ORDER BY ts DESC LIMIT 1
                ) p ON true
                ORDER BY s.sleeve_id
                """
            )
            return {"sleeves": [dict(r) for r in rows]}
    except Exception:  # noqa: BLE001
        return {"sleeves": []}


@app.get("/system/positions")
async def list_positions(sleeve_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            if sleeve_id:
                rows = await conn.fetch(
                    """
                    SELECT * FROM paper_positions
                    WHERE sleeve_id = $1 AND size > 0
                    ORDER BY opened_at DESC
                    """,
                    sleeve_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM paper_positions
                    WHERE size > 0
                    ORDER BY opened_at DESC
                    LIMIT 200
                    """
                )
            return {"positions": [dict(r) for r in rows]}
    except Exception:  # noqa: BLE001
        return {"positions": []}


@app.get("/system/recent_fills")
async def recent_fills(limit: int = Query(50, le=500)) -> dict[str, list[dict[str, Any]]]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT fill_id, sleeve_id, market_id, asset_id, side, price, size,
                       fill_type, ts_filled, realism_flag
                FROM paper_fills
                ORDER BY ts_filled DESC
                LIMIT $1
                """,
                limit,
            )
            return {"fills": [dict(r) for r in rows]}
    except Exception:  # noqa: BLE001
        return {"fills": []}


@app.get("/system/recent_trades")
async def recent_trades(limit: int = Query(50, le=500)) -> dict[str, list[dict[str, Any]]]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT trade_id, sleeve_id, strategy_name, config_id,
                       market_id, asset_id, side,
                       entry_price, exit_price, entry_size,
                       entry_ts, exit_ts,
                       pnl_usd, pnl_after_haircut_usd, realism_flag, fill_type, source
                FROM paper_trades
                ORDER BY entry_ts DESC
                LIMIT $1
                """,
                limit,
            )
            return {"trades": [dict(r) for r in rows]}
    except Exception:  # noqa: BLE001
        return {"trades": []}


@app.get("/system/sleeve_pnl")
async def sleeve_pnl(
    sleeve_id: str | None = None,
    hours: int = Query(72, ge=1, le=24 * 90),
) -> dict[str, list[dict[str, Any]]]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
            if sleeve_id:
                rows = await conn.fetch(
                    """
                    SELECT * FROM sleeve_pnl_snapshots
                    WHERE sleeve_id = $1 AND ts >= $2
                    ORDER BY ts ASC
                    """,
                    sleeve_id,
                    since,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM sleeve_pnl_snapshots
                    WHERE ts >= $1
                    ORDER BY sleeve_id, ts ASC
                    """,
                    since,
                )
            return {"points": [dict(r) for r in rows]}
    except Exception:  # noqa: BLE001
        return {"points": []}


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
