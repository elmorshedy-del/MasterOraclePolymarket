"""Writers for sleeve / signal / order / fill / trade rows.

These are call-site convenience helpers used by the runner. Each function
takes a single object and persists it. Batched writers can be added later
if individual writes become a bottleneck (Phase 2 expects modest fill
volume; the EventWriter remains the high-throughput path).
"""

from __future__ import annotations

import logging
from typing import Any

import orjson

from src.core.events import Fill, Order, Signal, Trade
from src.db.connection import get_pool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sleeve registration / mode tracking
# ---------------------------------------------------------------------------


async def upsert_sleeve(
    sleeve_id: str,
    strategy_name: str,
    config_id: str,
    edge_class: str | None,
    starting_capital_usd: float,
    mode: str,
    enabled: bool,
    config_hash: str,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Audit Med-2: previously last_mode_change_at = now() on EVERY upsert,
        # so each runner boot reset the gate's day-count to zero. Promotion
        # gates (live_log → live_signal needs ≥14 days) became impossible to
        # ever satisfy. Now that timestamp only advances when mode actually
        # changes; otherwise we keep the existing value.
        await conn.execute(
            """
            INSERT INTO sleeves
                (sleeve_id, strategy_name, config_id, edge_class,
                 starting_capital_usd, mode, enabled, config_hash)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (sleeve_id) DO UPDATE SET
                strategy_name = EXCLUDED.strategy_name,
                config_id     = EXCLUDED.config_id,
                edge_class    = EXCLUDED.edge_class,
                starting_capital_usd = EXCLUDED.starting_capital_usd,
                mode          = EXCLUDED.mode,
                enabled       = EXCLUDED.enabled,
                config_hash   = EXCLUDED.config_hash,
                last_mode_change_at = CASE
                    WHEN sleeves.mode IS DISTINCT FROM EXCLUDED.mode THEN now()
                    ELSE sleeves.last_mode_change_at
                END
            """,
            sleeve_id,
            strategy_name,
            config_id,
            edge_class,
            starting_capital_usd,
            mode,
            enabled,
            config_hash,
        )


async def record_mode_change(
    sleeve_id: str,
    from_mode: str | None,
    to_mode: str,
    config_hash: str,
    reason: str | None = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sleeve_mode_history
                (sleeve_id, from_mode, to_mode, config_hash, reason)
            VALUES ($1, $2, $3, $4, $5)
            """,
            sleeve_id,
            from_mode,
            to_mode,
            config_hash,
            reason,
        )


# ---------------------------------------------------------------------------
# Signals / orders / fills / trades
# ---------------------------------------------------------------------------


async def insert_signal(signal: Signal) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO signals
                (signal_id, sleeve_id, strategy_name, config_id,
                 market_id, asset_id, side, order_type, price, size,
                 reason, ts_signal, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb)
            ON CONFLICT (signal_id) DO NOTHING
            """,
            signal.signal_id,
            signal.sleeve_id,
            signal.strategy_name,
            signal.config_id,
            signal.market_id,
            signal.asset_id,
            signal.side.value,
            signal.order_type.value,
            float(signal.price) if signal.price is not None else None,
            float(signal.size),
            signal.reason,
            signal.ts_signal,
            orjson.dumps(_jsonable(signal.metadata)).decode(),
        )


async def insert_order(order: Order) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO paper_orders
                (order_id, signal_id, sleeve_id, market_id, asset_id,
                 side, order_type, price, size, ts_signal, ts_placed,
                 status, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'open', $12::jsonb)
            ON CONFLICT (order_id) DO NOTHING
            """,
            order.order_id,
            order.signal_id,
            order.sleeve_id,
            order.market_id,
            order.asset_id,
            order.side.value,
            order.order_type.value,
            float(order.price) if order.price is not None else None,
            float(order.size),
            order.ts_signal,
            order.ts_placed,
            orjson.dumps(_jsonable(order.metadata)).decode(),
        )


async def insert_fill(fill: Fill) -> None:
    """Insert a fill row and reconcile the parent order's status.

    Audit Med-6: previously every fill set the order to 'filled' regardless
    of whether the cumulative filled size matched the order size. Partial
    fills (size < order.size) were misreported as fully filled. Now we
    aggregate fills against paper_orders.size and pick:

      missed       → cancelled
      Σ size >= order.size → filled
      0 < Σ size < order.size → partially_filled
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO paper_fills
                (fill_id, order_id, sleeve_id, market_id, asset_id,
                 side, price, size, fill_type, ts_filled, realism_flag,
                 gas_cost_usd, slippage_bps, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14::jsonb)
            ON CONFLICT (fill_id) DO NOTHING
            """,
            fill.fill_id,
            fill.order_id,
            fill.sleeve_id,
            fill.market_id,
            fill.asset_id,
            fill.side.value,
            float(fill.price),
            float(fill.size),
            fill.fill_type.value,
            fill.ts_filled,
            fill.realism_flag.value,
            float(fill.gas_cost),
            float(fill.slippage_bps) if fill.slippage_bps is not None else None,
            orjson.dumps(_jsonable(fill.metadata)).decode(),
        )

        if fill.fill_type.value == "missed":
            new_status = "cancelled"
            await conn.execute(
                "UPDATE paper_orders SET status = $1 WHERE order_id = $2 AND status = 'open'",
                new_status, fill.order_id,
            )
            return

        # Reconcile against the order's cumulative filled size
        await conn.execute(
            """
            UPDATE paper_orders po
            SET status = CASE
              WHEN agg.filled_size >= po.size THEN 'filled'
              WHEN agg.filled_size > 0 THEN 'partially_filled'
              ELSE 'open'
            END
            FROM (
                SELECT order_id, COALESCE(SUM(size), 0) AS filled_size
                FROM paper_fills
                WHERE order_id = $1 AND fill_type IN ('taker', 'maker_fast', 'maker_slow')
                GROUP BY order_id
            ) agg
            WHERE po.order_id = $1 AND agg.order_id = po.order_id
            """,
            fill.order_id,
        )


async def upsert_position(
    sleeve_id: str,
    market_id: str,
    asset_id: str,
    side: str,
    size: float,
    avg_entry: float,
    opened_at,
) -> None:
    """Upsert an open paper_positions row. ``size <= 0`` deletes the row."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if size > 0:
            await conn.execute(
                """
                INSERT INTO paper_positions
                  (sleeve_id, market_id, asset_id, side, size, avg_entry, opened_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (sleeve_id, market_id, asset_id, side) DO UPDATE SET
                  size = EXCLUDED.size,
                  avg_entry = EXCLUDED.avg_entry,
                  last_updated = now()
                """,
                sleeve_id, market_id, asset_id, side, size, avg_entry, opened_at,
            )
        else:
            await conn.execute(
                """
                DELETE FROM paper_positions
                WHERE sleeve_id = $1 AND market_id = $2 AND asset_id = $3 AND side = $4
                """,
                sleeve_id, market_id, asset_id, side,
            )


async def upsert_market_meta(
    market_id: str,
    venue: str,
    venue_market_id: str,
    title: str,
    category: str,
    subcategory: str | None,
    end_time,
    tick_size: float,
    asset_ids: list[str],
    tags_extra: dict[str, Any],
) -> None:
    """Persist a market into the markets table for tag enrichment."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO markets
              (market_id, venue, venue_market_id, title, category, subcategory,
               end_time, tick_size, asset_ids, tags_extra)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
            ON CONFLICT (venue, venue_market_id) DO UPDATE SET
              title = EXCLUDED.title,
              category = EXCLUDED.category,
              subcategory = EXCLUDED.subcategory,
              end_time = EXCLUDED.end_time,
              tick_size = EXCLUDED.tick_size,
              asset_ids = EXCLUDED.asset_ids,
              tags_extra = EXCLUDED.tags_extra,
              last_seen_at = now()
            """,
            market_id, venue, venue_market_id, title, category, subcategory,
            end_time, tick_size, asset_ids,
            orjson.dumps(_jsonable(tags_extra)).decode(),
        )


async def insert_trade(trade: Trade, config_hash: str, source: str = "live") -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO paper_trades
                (trade_id, sleeve_id, strategy_name, config_id, config_hash,
                 market_id, asset_id, side,
                 entry_price, entry_size, entry_ts,
                 exit_price, exit_size, exit_ts,
                 pnl_usd, pnl_after_haircut_usd,
                 realism_flag, fill_type, slippage_bps,
                 tags_extra, source)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8,
                    $9, $10, $11, $12, $13, $14,
                    $15, $16, $17, $18, $19, $20::jsonb, $21)
            ON CONFLICT (trade_id) DO NOTHING
            """,
            trade.trade_id,
            trade.sleeve_id,
            trade.strategy_name,
            trade.config_id,
            config_hash,
            trade.market_id,
            trade.asset_id,
            trade.side.value,
            float(trade.entry_price),
            float(trade.entry_size),
            trade.entry_ts,
            float(trade.exit_price) if trade.exit_price is not None else None,
            float(trade.exit_size) if trade.exit_size is not None else None,
            trade.exit_ts,
            float(trade.pnl) if trade.pnl is not None else None,
            float(trade.pnl_after_haircut) if trade.pnl_after_haircut is not None else None,
            trade.realism_flag.value,
            trade.fill_type.value,
            float(trade.slippage_bps) if trade.slippage_bps is not None else None,
            orjson.dumps(_jsonable(trade.tags)).decode(),
            source,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jsonable(obj: Any) -> Any:
    from decimal import Decimal
    from uuid import UUID

    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    return obj
