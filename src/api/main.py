"""FastAPI surface for the dashboard.

Phase 3 endpoints:
  - System / health (Phase 1+2)
  - GET /system/sleeves, /system/positions, /system/recent_fills, /system/recent_trades, /system/sleeve_pnl
  - GET /analytics/pivot          — group-by P&L heatmap data
  - GET /analytics/sleeve_metrics — full metric scorecard for a sleeve
  - GET /analytics/failure_modes  — losers grouped by failure category
  - GET /analytics/strategies     — strategies known to the runner (for Strategy Lab)
  - POST /replay/run              — submit a replay job
  - GET  /replay/jobs             — list jobs
  - GET  /replay/jobs/{id}        — status + result for a single job
  - GET  /replay/runs             — completed replay runs (from DB)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.analytics.metric_service import MetricService
from src.analytics.tag_service import _row_to_trade
from src.db.connection import get_pool
from src.runner.promotion_gates import PromotionEvaluator
from src.runner.replay_engine import ReplayOverrides
from src.runner.replay_queue import ReplayJob, get_queue
from src.venues._orderbook_store import STORE

app = FastAPI(title="Master Paper Trade Lab API", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health / system
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
async def version() -> dict[str, str]:
    return {"version": "0.3.0", "phase": "3"}


@app.on_event("startup")
async def _on_startup() -> None:
    await get_queue().start()


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    await get_queue().stop()


@app.get("/system/health")
async def system_health() -> dict[str, object]:
    db_status = "unknown"
    db_now: str | None = None
    metrics: dict[str, Any] = {}
    orderbook_metrics = {
        "markets_seen": 0,
        "asset_books_seen": 0,
        "book_snapshots": 0,
        "book_deltas": 0,
    }
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT now() AS now")
            db_now = row["now"].isoformat() if row else None
            db_status = "ok"
            metrics["events_last_5min"] = await conn.fetchval(
                "SELECT count(*) FROM market_events WHERE ts > now() - interval '5 minutes'"
            )
            metrics["fills_last_1h"] = await conn.fetchval(
                "SELECT count(*) FROM paper_fills WHERE ts_filled > now() - interval '1 hour'"
            )
            metrics["trades_last_1h"] = await conn.fetchval(
                "SELECT count(*) FROM paper_trades WHERE entry_ts > now() - interval '1 hour'"
            )
            metrics["open_positions"] = await conn.fetchval(
                "SELECT count(*) FROM paper_positions WHERE size > 0"
            )
            orderbook_row = await conn.fetchrow(
                """
                SELECT
                    count(DISTINCT market_id) FILTER (
                        WHERE event_type IN ('book_snapshot', 'book_delta', 'trade_print')
                          AND market_id IS NOT NULL
                    ) AS markets_seen,
                    count(DISTINCT market_id || ':' || asset_id) FILTER (
                        WHERE event_type IN ('book_snapshot', 'book_delta', 'trade_print')
                          AND market_id IS NOT NULL
                          AND asset_id IS NOT NULL
                    ) AS asset_books_seen,
                    count(*) FILTER (WHERE event_type = 'book_snapshot') AS book_snapshots,
                    count(*) FILTER (WHERE event_type = 'book_delta') AS book_deltas
                FROM market_events
                WHERE ts > now() - interval '5 minutes'
                """
            )
            if orderbook_row is not None:
                orderbook_metrics = {
                    key: int(orderbook_row[key] or 0)
                    for key in orderbook_metrics
                }
    except Exception as exc:
        db_status = f"error: {exc!s}"

    markets_count = STORE.market_count() or orderbook_metrics["markets_seen"]
    asset_books_count = STORE.asset_count() or orderbook_metrics["asset_books_seen"]
    snapshots_count = STORE.snapshots_applied or orderbook_metrics["book_snapshots"]
    deltas_count = STORE.deltas_applied or orderbook_metrics["book_deltas"]

    return {
        "checked_at": datetime.now(tz=UTC).isoformat(),
        "db": {"status": db_status, "server_time": db_now, **metrics},
        "orderbooks": {
            "markets_in_memory": markets_count,
            "asset_books_in_memory": asset_books_count,
            "snapshots_applied_total": snapshots_count,
            "deltas_applied_total": deltas_count,
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
                       s.starting_capital_usd, s.mode, s.enabled, s.config_hash, s.started_at,
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
    except Exception:
        return {"sleeves": []}


@app.get("/system/positions")
async def list_positions(sleeve_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            if sleeve_id:
                rows = await conn.fetch(
                    "SELECT * FROM paper_positions WHERE sleeve_id = $1 AND size > 0 ORDER BY opened_at DESC",
                    sleeve_id,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM paper_positions WHERE size > 0 ORDER BY opened_at DESC LIMIT 200"
                )
            return {"positions": [dict(r) for r in rows]}
    except Exception:
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
                FROM paper_fills ORDER BY ts_filled DESC LIMIT $1
                """,
                limit,
            )
            return {"fills": [dict(r) for r in rows]}
    except Exception:
        return {"fills": []}


@app.get("/system/recent_trades")
async def recent_trades(
    limit: int = Query(50, le=500),
    sleeve_id: str | None = None,
    source: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            params: list[Any] = []
            wheres: list[str] = []
            if sleeve_id:
                params.append(sleeve_id)
                wheres.append(f"sleeve_id = ${len(params)}")
            if source:
                params.append(source)
                wheres.append(f"source = ${len(params)}")
            where_clause = "WHERE " + " AND ".join(wheres) if wheres else ""
            params.append(limit)
            rows = await conn.fetch(
                f"""
                SELECT trade_id, sleeve_id, strategy_name, config_id,
                       market_id, asset_id, side,
                       entry_price, exit_price, entry_size,
                       entry_ts, exit_ts,
                       pnl_usd, pnl_after_haircut_usd, realism_flag, fill_type, source,
                       market_category, market_subcategory, liquidity_bucket, entry_price_bucket,
                       time_to_resolution_bucket, orderbook_state_bucket, time_of_day_bucket,
                       day_of_week, news_regime, counterparty_estimate
                FROM paper_trades {where_clause}
                ORDER BY entry_ts DESC LIMIT ${len(params)}
                """,
                *params,
            )
            return {"trades": [dict(r) for r in rows]}
    except Exception:
        return {"trades": []}


@app.get("/system/sleeve_pnl")
async def sleeve_pnl(
    sleeve_id: str | None = None,
    hours: int = Query(72, ge=1, le=24 * 90),
) -> dict[str, list[dict[str, Any]]]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            since = datetime.now(tz=UTC) - timedelta(hours=hours)
            if sleeve_id:
                rows = await conn.fetch(
                    "SELECT * FROM sleeve_pnl_snapshots WHERE sleeve_id = $1 AND ts >= $2 ORDER BY ts ASC",
                    sleeve_id,
                    since,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM sleeve_pnl_snapshots WHERE ts >= $1 ORDER BY sleeve_id, ts ASC",
                    since,
                )
            return {"points": [dict(r) for r in rows]}
    except Exception:
        return {"points": []}


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


_PIVOT_COLUMNS = {
    "strategy_name", "config_id", "market_category", "market_subcategory",
    "liquidity_bucket", "entry_price_bucket", "time_to_resolution_bucket",
    "orderbook_state_bucket", "time_of_day_bucket", "day_of_week",
    "news_regime", "counterparty_estimate", "fill_type", "realism_flag", "source",
}


@app.get("/analytics/pivot")
async def analytics_pivot(
    row: str = Query("strategy_name"),
    col: str = Query("market_category"),
    metric: str = Query("total_pnl"),
    hours: int = Query(168, ge=1, le=24 * 365),
) -> dict[str, Any]:
    """Group-by aggregation over paper_trades.

    Returns a list of cells: ``[{row_key, col_key, total_pnl, trade_count, win_rate, avg_pnl}]``
    The frontend renders these as a heatmap.
    """
    if row not in _PIVOT_COLUMNS or col not in _PIVOT_COLUMNS:
        raise HTTPException(400, "row/col must be one of the supported tag columns")
    metric = metric if metric in {"total_pnl", "trade_count", "win_rate", "avg_pnl"} else "total_pnl"

    try:
        pool = await get_pool()
    except RuntimeError:
        return {"row_dim": row, "col_dim": col, "metric": metric, "cells": []}

    since = datetime.now(tz=UTC) - timedelta(hours=hours)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                {row} AS row_key,
                {col} AS col_key,
                COALESCE(SUM(pnl_after_haircut_usd), 0)::float AS total_pnl,
                COUNT(*) AS trade_count,
                AVG(CASE WHEN pnl_after_haircut_usd > 0 THEN 1.0 ELSE 0.0 END)::float AS win_rate,
                AVG(pnl_after_haircut_usd)::float AS avg_pnl
            FROM paper_trades
            WHERE entry_ts >= $1
            GROUP BY {row}, {col}
            ORDER BY {row}, {col}
            """,
            since,
        )
        return {
            "row_dim": row,
            "col_dim": col,
            "metric": metric,
            "since": since.isoformat(),
            "cells": [dict(r) for r in rows],
        }


@app.get("/analytics/sleeve_metrics")
async def sleeve_metrics(sleeve_id: str) -> dict[str, Any]:
    try:
        pool = await get_pool()
    except RuntimeError:
        return {"sleeve_id": sleeve_id, "metrics": {}, "trade_count": 0}

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT trade_id, sleeve_id, strategy_name, config_id, market_id, asset_id, side,
                   entry_price, entry_size, entry_ts,
                   exit_price, exit_size, exit_ts,
                   pnl_usd, pnl_after_haircut_usd, realism_flag, fill_type, tags_extra
            FROM paper_trades WHERE sleeve_id = $1
            """,
            sleeve_id,
        )

    trades = [_row_to_trade(r) for r in rows]
    metrics = MetricService().compute_all(trades)
    return {"sleeve_id": sleeve_id, "trade_count": len(trades), "metrics": metrics}


@app.get("/analytics/failure_modes")
async def failure_modes(
    sleeve_id: str | None = None,
    hours: int = Query(168, ge=1, le=24 * 365),
) -> dict[str, Any]:
    """Breakdown of LOSING trades by failure category.

    V1 categories:
      - implausible: realism_flag = 'implausible'
      - picked_off: realism_flag = 'picked_off'
      - thin_market: realism_flag = 'thin_market'
      - moved_market: realism_flag = 'would_have_moved_market'
      - missed_fill: fill_type = 'missed'
      - regular_loss: clean fills that just lost
    """
    try:
        pool = await get_pool()
    except RuntimeError:
        return {"buckets": []}

    since = datetime.now(tz=UTC) - timedelta(hours=hours)
    async with pool.acquire() as conn:
        params: list[Any] = [since]
        sleeve_clause = ""
        if sleeve_id:
            params.append(sleeve_id)
            sleeve_clause = f"AND sleeve_id = ${len(params)}"
        rows = await conn.fetch(
            f"""
            SELECT
                CASE
                    WHEN realism_flag = 'implausible' THEN 'implausible'
                    WHEN realism_flag = 'picked_off' THEN 'picked_off'
                    WHEN realism_flag = 'thin_market' THEN 'thin_market'
                    WHEN realism_flag = 'would_have_moved_market' THEN 'moved_market'
                    WHEN fill_type = 'missed' THEN 'missed_fill'
                    ELSE 'regular_loss'
                END AS bucket,
                COUNT(*) AS trade_count,
                COALESCE(SUM(pnl_after_haircut_usd), 0)::float AS total_pnl,
                COALESCE(AVG(pnl_after_haircut_usd), 0)::float AS avg_pnl
            FROM paper_trades
            WHERE entry_ts >= $1
              AND pnl_after_haircut_usd < 0
              {sleeve_clause}
            GROUP BY bucket
            ORDER BY total_pnl ASC
            """,
            *params,
        )
        return {"buckets": [dict(r) for r in rows]}


@app.get("/analytics/strategies")
async def list_strategies() -> dict[str, list[dict[str, Any]]]:
    """Strategies discovered by the plugin loader — for Strategy Lab dropdowns."""
    from pathlib import Path

    from src.core import plugin_loader
    plugins = plugin_loader.discover_all(Path(__file__).resolve().parents[2])
    return {
        "strategies": [
            {
                "name": p.name,
                "edge_class": getattr(p.instance, "edge_class", None),
                "module_path": str(p.module_path),
            }
            for p in plugins
            if p.kind == "strategy"
        ]
    }


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


class ReplayRequest(BaseModel):
    strategy_name: str
    config_id: str = "default"
    days: int | None = Field(default=30, ge=1, le=365)
    range_start: datetime | None = None
    range_end: datetime | None = None
    starting_capital: float = 5000.0
    edge_class: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)


@app.post("/replay/run")
async def replay_run(req: ReplayRequest) -> dict[str, Any]:
    queue = get_queue()
    range_end = req.range_end or datetime.now(tz=UTC)
    range_start = req.range_start or (range_end - timedelta(days=req.days or 30))

    overrides = ReplayOverrides()
    if "latency_ms" in req.overrides:
        overrides.latency_ms = int(req.overrides["latency_ms"])
    if "size_multiplier" in req.overrides:
        overrides.size_multiplier = Decimal(str(req.overrides["size_multiplier"]))
    if "haircut_override" in req.overrides:
        overrides.haircut_override = Decimal(str(req.overrides["haircut_override"]))
    if "market_filter" in req.overrides:
        mf = req.overrides["market_filter"]
        if isinstance(mf, list):
            overrides.market_filter = [str(x) for x in mf]

    job = ReplayJob(
        job_id=uuid4(),
        strategy_name=req.strategy_name,
        config_id=req.config_id,
        range_start=range_start,
        range_end=range_end,
        starting_capital=Decimal(str(req.starting_capital)),
        edge_class=req.edge_class,
        overrides=overrides,
    )
    queue.submit(job)
    return _job_to_dict(job)


@app.get("/replay/jobs")
async def list_replay_jobs(limit: int = Query(50, le=200)) -> dict[str, list[dict[str, Any]]]:
    return {"jobs": [_job_to_dict(j) for j in get_queue().list(limit=limit)]}


@app.get("/replay/jobs/{job_id}")
async def get_replay_job(job_id: UUID) -> dict[str, Any]:
    job = get_queue().get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return _job_to_dict(job)


@app.get("/replay/runs")
async def list_replay_runs(limit: int = Query(50, le=500)) -> dict[str, list[dict[str, Any]]]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT run_id, sleeve_id, strategy_name, config_id, range_start, range_end,
                       started_at, finished_at, status, summary
                FROM replay_runs
                ORDER BY started_at DESC LIMIT $1
                """,
                limit,
            )
            return {"runs": [dict(r) for r in rows]}
    except Exception:
        return {"runs": []}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job_to_dict(job: ReplayJob) -> dict[str, Any]:
    return {
        "job_id": str(job.job_id),
        "strategy_name": job.strategy_name,
        "config_id": job.config_id,
        "status": job.status,
        "submitted_at": job.submitted_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "range_start": job.range_start.isoformat() if job.range_start else None,
        "range_end": job.range_end.isoformat() if job.range_end else None,
        "error": job.error,
        "result": (
            None if job.result is None else {
                "run_id": str(job.result.run_id),
                "signals": job.result.signals,
                "fills": job.result.fills,
                "trades": job.result.trades,
                "realized_pnl": str(job.result.realized_pnl),
                "metrics": job.result.metrics,
            }
        ),
    }


# ---------------------------------------------------------------------------
# Promotion gates
# ---------------------------------------------------------------------------


@app.get("/promotion/check")
async def promotion_check(sleeve_id: str) -> dict[str, Any]:
    """Evaluate promotion gates for a sleeve.

    Returns the current mode, the next-mode candidate, per-criterion pass/fail,
    and kill-criteria status (when current_mode is live_full).
    """
    evaluator = PromotionEvaluator()
    result = await evaluator.evaluate(sleeve_id)
    return result.as_dict()


@app.get("/system/markets/count")
async def markets_count() -> dict[str, int]:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT count(*) AS c FROM markets")
            return {"count": int(row["c"]) if row else 0}
    except Exception:
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
