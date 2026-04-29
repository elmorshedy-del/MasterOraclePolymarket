"""Tag application service.

Two responsibilities:
  1. Apply all enabled Tag plugins to every Trade as it lands.
  2. Provide a retroactive backfill function for Trades created before a
     new Tag plugin was added.

The plugin loader auto-discovers Tag plugins. The service builds a
TagContext per trade by querying the DB for surrounding state (market
meta, book at entry approximated from nearest event, news count in window,
counterparty heuristic from public activity feed).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import orjson

from src.core import plugin_loader
from src.core.events import OrderBook, PriceLevel, Side, Trade
from src.core.interfaces import Tag
from src.db.connection import get_pool

logger = logging.getLogger(__name__)


REPO_ROOT = Path(__file__).resolve().parents[2]


# Tags that have first-class denormalized columns on paper_trades.
# All other tag plugins write to the tags_extra JSONB blob.
COLUMN_TAGS = {
    "market_category",
    "market_subcategory",
    "liquidity_bucket",
    "entry_price_bucket",
    "time_to_resolution_bucket",
    "orderbook_state_bucket",
    "time_of_day_bucket",
    "day_of_week",
    "news_regime",
    "counterparty_estimate",
}


class TagService:
    def __init__(self) -> None:
        plugins = plugin_loader.discover_all(REPO_ROOT)
        self.tags: list[Tag] = [p.instance for p in plugins if p.kind == "tag"]
        self.tags.sort(key=lambda t: t.name)
        logger.info("tag service loaded %d tags: %s",
                    len(self.tags), [t.name for t in self.tags])

    # ------------------------------------------------------------------------
    # Live tagging
    # ------------------------------------------------------------------------

    async def tag_and_persist(self, trade: Trade) -> None:
        """Apply all tags to ``trade`` and write back to paper_trades row."""
        try:
            context = await self._build_context(trade)
        except Exception:  # noqa: BLE001
            logger.exception("failed to build tag context for trade %s", trade.trade_id)
            return

        column_values: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        for t in self.tags:
            try:
                value = t.tag_trade(trade, context)
            except Exception:  # noqa: BLE001
                logger.exception("tag %s raised on trade %s", t.name, trade.trade_id)
                continue
            if value is None:
                continue
            if t.name in COLUMN_TAGS:
                column_values[t.name] = value
            else:
                extra[t.name] = value

        await self._update_trade_tags(trade.trade_id, column_values, extra)

    # ------------------------------------------------------------------------
    # Retroactive backfill
    # ------------------------------------------------------------------------

    async def backfill_recent(self, hours: int = 24, limit: int = 5000) -> int:
        """Re-tag trades closed in the last N hours. Returns count tagged."""
        since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
        try:
            pool = await get_pool()
        except RuntimeError:
            return 0

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT trade_id, sleeve_id, strategy_name, config_id,
                       market_id, asset_id, side,
                       entry_price, entry_size, entry_ts,
                       exit_price, exit_size, exit_ts,
                       pnl_usd, pnl_after_haircut_usd,
                       realism_flag, fill_type, tags_extra
                FROM paper_trades
                WHERE entry_ts >= $1
                ORDER BY entry_ts DESC
                LIMIT $2
                """,
                since,
                limit,
            )

        count = 0
        for r in rows:
            trade = _row_to_trade(r)
            await self.tag_and_persist(trade)
            count += 1
        return count

    # ------------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------------

    async def _build_context(self, trade: Trade) -> dict[str, Any]:
        ctx: dict[str, Any] = {}

        try:
            pool = await get_pool()
        except RuntimeError:
            return ctx

        async with pool.acquire() as conn:
            # Market meta
            mrow = await conn.fetchrow(
                """
                SELECT category, subcategory, end_time, tags_extra
                FROM markets
                WHERE market_id = $1
                """,
                trade.market_id,
            )
            if mrow is not None:
                ctx["market_category"] = mrow["category"]
                ctx["market_subcategory"] = mrow["subcategory"]
                ctx["end_time"] = mrow["end_time"]
                tags_extra = mrow["tags_extra"] or {}
                if isinstance(tags_extra, str):
                    try:
                        tags_extra = orjson.loads(tags_extra)
                    except Exception:  # noqa: BLE001
                        tags_extra = {}
                vol = tags_extra.get("volume_24h") if isinstance(tags_extra, dict) else None
                if vol is not None:
                    try:
                        ctx["volume_24h_usd"] = Decimal(str(vol))
                    except Exception:  # noqa: BLE001
                        pass

            # Book at entry — from nearest BOOK_SNAPSHOT in the 60s before entry
            book_row = await conn.fetchrow(
                """
                SELECT payload FROM market_events
                WHERE event_type = 'book_snapshot'
                  AND market_id = $1 AND asset_id = $2
                  AND ts <= $3 AND ts > $3 - interval '60 seconds'
                ORDER BY ts DESC LIMIT 1
                """,
                trade.market_id,
                trade.asset_id,
                trade.entry_ts,
            )
            if book_row is not None:
                payload = book_row["payload"]
                if isinstance(payload, str):
                    try:
                        payload = orjson.loads(payload)
                    except Exception:  # noqa: BLE001
                        payload = {}
                ctx["book_at_entry"] = _payload_to_book(trade.market_id, trade.asset_id, payload)

            # News count in 5 minutes before entry
            news_count = await conn.fetchval(
                """
                SELECT count(*) FROM market_events
                WHERE event_type = 'news_item'
                  AND ts >= $1 - interval '5 minutes'
                  AND ts <= $1
                """,
                trade.entry_ts,
            )
            ctx["pre_entry_news_count"] = int(news_count or 0)

            # Counterparty wallet — look for an opposing-side activity event
            # in a 30s window around entry
            cp = await conn.fetchrow(
                """
                SELECT payload FROM market_events
                WHERE event_type = 'activity_trade'
                  AND market_id = $1 AND asset_id = $2
                  AND ts >= $3 - interval '30 seconds'
                  AND ts <= $3 + interval '30 seconds'
                ORDER BY abs(extract(epoch from (ts - $3))) ASC
                LIMIT 1
                """,
                trade.market_id,
                trade.asset_id,
                trade.entry_ts,
            )
            if cp is not None:
                p = cp["payload"]
                if isinstance(p, str):
                    try:
                        p = orjson.loads(p)
                    except Exception:  # noqa: BLE001
                        p = {}
                if isinstance(p, dict):
                    ctx["counterparty_wallet"] = p.get("wallet")

        return ctx

    async def _update_trade_tags(
        self,
        trade_id,
        column_values: dict[str, Any],
        extra: dict[str, Any],
    ) -> None:
        if not column_values and not extra:
            return

        try:
            pool = await get_pool()
        except RuntimeError:
            return

        # Build dynamic UPDATE — only set columns we have values for.
        sets: list[str] = []
        args: list[Any] = []
        idx = 1
        for col in (
            "market_category",
            "market_subcategory",
            "liquidity_bucket",
            "entry_price_bucket",
            "time_to_resolution_bucket",
            "orderbook_state_bucket",
            "time_of_day_bucket",
            "day_of_week",
            "news_regime",
            "counterparty_estimate",
        ):
            if col in column_values:
                sets.append(f"{col} = ${idx}")
                args.append(column_values[col])
                idx += 1

        if extra:
            sets.append(f"tags_extra = tags_extra || ${idx}::jsonb")
            args.append(orjson.dumps(extra).decode())
            idx += 1

        if not sets:
            return

        args.append(trade_id)
        sql = f"UPDATE paper_trades SET {', '.join(sets)} WHERE trade_id = ${idx}"

        async with pool.acquire() as conn:
            await conn.execute(sql, *args)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _payload_to_book(market_id: str, asset_id: str, payload: dict[str, Any]) -> OrderBook | None:
    try:
        bids = [
            PriceLevel(price=Decimal(str(b["price"])), size=Decimal(str(b["size"])))
            for b in payload.get("bids", [])
        ]
        asks = [
            PriceLevel(price=Decimal(str(a["price"])), size=Decimal(str(a["size"])))
            for a in payload.get("asks", [])
        ]
    except Exception:  # noqa: BLE001
        return None
    return OrderBook(market_id=market_id, asset_id=asset_id, bids=bids, asks=asks)


def _row_to_trade(r) -> Trade:
    from uuid import UUID

    from src.core.events import FillType, RealismFlag

    return Trade(
        trade_id=r["trade_id"] if isinstance(r["trade_id"], UUID) else UUID(str(r["trade_id"])),
        sleeve_id=r["sleeve_id"],
        strategy_name=r["strategy_name"],
        config_id=r["config_id"],
        market_id=r["market_id"],
        asset_id=r["asset_id"],
        side=Side(r["side"]),
        entry_price=Decimal(str(r["entry_price"])),
        entry_size=Decimal(str(r["entry_size"])),
        entry_ts=r["entry_ts"],
        exit_price=Decimal(str(r["exit_price"])) if r["exit_price"] is not None else None,
        exit_size=Decimal(str(r["exit_size"])) if r["exit_size"] is not None else None,
        exit_ts=r["exit_ts"],
        pnl=Decimal(str(r["pnl_usd"])) if r["pnl_usd"] is not None else None,
        pnl_after_haircut=Decimal(str(r["pnl_after_haircut_usd"])) if r["pnl_after_haircut_usd"] is not None else None,
        realism_flag=RealismFlag(r["realism_flag"]),
        fill_type=FillType(r["fill_type"]),
        tags=r.get("tags_extra") or {},
    )
