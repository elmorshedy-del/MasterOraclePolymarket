"""Replay engine — run any strategy against recorded events.

Reads ``market_events`` rows for a (market subset, time range), reconstructs
order book state, runs the chosen Strategy through the events, routes
signals through a fresh FillSimulator + PositionTracker, and writes results
to ``replay_runs`` and ``paper_trades`` (with ``source = 'replay'``).

Param overrides supported:
  - latency_ms: total end-to-end latency
  - size_multiplier: scale all signal sizes by a factor
  - cancel_decay: maker queue cancel-credit factor
  - haircut_override: override per-edge-class haircut
  - market_filter: list of market_ids to restrict to

The replay is fully in-memory (one process, no DB writes during simulation
except the final batch of trade rows). It uses the SAME fill simulator
class as the live runner, so behavior matches.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import orjson

from src.core import plugin_loader
from src.core.events import (
    EventType,
    MarketEvent,
    Order,
    OrderBook,
    PriceLevel,
    Side,
    Signal,
)
from src.core.interfaces import Strategy
from src.db import writers as db_writers
from src.db.connection import get_pool
from src.execution.event_replay import EventReplayFillSimulator
from src.execution.position_tracker import PositionTracker

logger = logging.getLogger(__name__)


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ReplayOverrides:
    latency_ms: int | None = None
    size_multiplier: Decimal = Decimal("1.0")
    cancel_decay: Decimal | None = None
    haircut_override: Decimal | None = None
    market_filter: list[str] = field(default_factory=list)


@dataclass
class ReplayResult:
    run_id: UUID
    strategy_name: str
    config_id: str
    config_hash: str
    range_start: datetime
    range_end: datetime
    signals: int
    fills: int
    trades: int
    realized_pnl: Decimal
    metrics: dict[str, float] = field(default_factory=dict)


class ReplayEngine:
    def __init__(self) -> None:
        plugins = plugin_loader.discover_all(REPO_ROOT)
        self._strategies: dict[str, Strategy] = {
            p.name: p.instance for p in plugins if p.kind == "strategy"
        }
        logger.info("replay engine knows %d strategies", len(self._strategies))

    async def run(
        self,
        strategy_name: str,
        config_id: str = "default",
        config_hash: str = "replay",
        sleeve_id: str | None = None,
        range_start: datetime | None = None,
        range_end: datetime | None = None,
        starting_capital: Decimal = Decimal("5000"),
        edge_class: str | None = None,
        overrides: ReplayOverrides | None = None,
    ) -> ReplayResult:
        if strategy_name not in self._strategies:
            raise ValueError(f"unknown strategy: {strategy_name}")
        template = self._strategies[strategy_name]
        overrides = overrides or ReplayOverrides()

        # Resolve sleeve YAML params for this (strategy, config_id). Replay
        # is config-true: aggressive / conservative / etc. produce DIFFERENT
        # results because they construct the strategy with different params.
        sleeve_params: dict[str, Any] = {}
        sleeve_edge_class = edge_class
        try:
            from src.core import config as cfg
            for ls in cfg.load_sleeves(REPO_ROOT / "src" / "configs" / "sleeves"):
                if (
                    ls.sleeve.strategy == strategy_name
                    and ls.sleeve.config_id == config_id
                ):
                    sleeve_params = dict(ls.sleeve.params or {})
                    if sleeve_edge_class is None and ls.sleeve.edge_class:
                        sleeve_edge_class = ls.sleeve.edge_class
                    break
        except Exception:
            logger.exception("failed to load sleeve params for %s/%s",
                             strategy_name, config_id)

        # Build a FRESH strategy per replay with the YAML params applied so
        # 'aggressive' actually fires more / sizes bigger, etc. Falls back
        # to default-constructed if the strategy rejects the kwargs.
        try:
            strategy = type(template)(**sleeve_params)
        except TypeError:
            try:
                strategy = type(template)()
            except TypeError:
                strategy = template
        if sleeve_edge_class is not None:
            edge_class = sleeve_edge_class

        if range_end is None:
            range_end = datetime.now(tz=UTC)
        if range_start is None:
            from datetime import timedelta
            range_start = range_end - timedelta(days=30)

        run_id = uuid4()
        sleeve_id = sleeve_id or f"replay__{strategy_name}__{config_id}__{run_id.hex[:6]}"

        # Persist run header
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO replay_runs
                        (run_id, sleeve_id, strategy_name, config_id, config_hash,
                         overrides, range_start, range_end, status)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, 'running')
                    """,
                    run_id,
                    sleeve_id,
                    strategy_name,
                    config_id,
                    config_hash,
                    orjson.dumps(_overrides_to_json(overrides)).decode(),
                    range_start,
                    range_end,
                )
                # Register the replay sleeve
                await db_writers.upsert_sleeve(
                    sleeve_id=sleeve_id,
                    strategy_name=strategy_name,
                    config_id=config_id,
                    edge_class=edge_class,
                    starting_capital_usd=float(starting_capital),
                    mode="replay_only",
                    enabled=True,
                    config_hash=config_hash,
                )
        except Exception:
            logger.exception("failed to register replay run %s", run_id)

        # Simulator + tracker
        latency_model = cfg.LatencyModel()
        if overrides.latency_ms is not None:
            # Distribute override evenly across the three latency segments
            third = overrides.latency_ms // 3
            latency_model = cfg.LatencyModel(
                decision_ms=third,
                code_path_ms=third,
                network_buffer_ms=overrides.latency_ms - 2 * third,
            )
        sim = EventReplayFillSimulator(latency=latency_model)
        if overrides.cancel_decay is not None:
            sim.cancel_decay = overrides.cancel_decay

        haircut_cfg = cfg.HaircutConfig()
        if overrides.haircut_override is not None:
            haircut_cfg = cfg.HaircutConfig(default=overrides.haircut_override)
        tracker = PositionTracker(haircut=haircut_cfg)
        tracker.register_sleeve(sleeve_id, starting_capital, edge_class=edge_class)

        # Replay state
        books: dict[tuple[str, str], OrderBook] = {}
        signals_count = 0
        fills_count = 0
        trades_count = 0
        trade_rows: list[tuple[Any, ...]] = []

        # Pending orders queued by latency (eta, order). Each iteration we
        # drain any whose eta has passed, then submit against the book state
        # AT THAT TIME. This is what makes the latency_ms override actually
        # affect replay fills — without this, orders always saw the
        # zero-latency book and the preset was misleading.
        from datetime import timedelta
        from heapq import heappop, heappush
        pending: list[tuple[datetime, Order]] = []
        latency_delay = timedelta(milliseconds=latency_model.total_ms())

        # PERSISTENT per-strategy state across the entire replay. Strategies
        # rely on this dict for in-strategy book reconstruction (book_state),
        # market-meta cache, cooldowns, active position sets, etc. Resetting
        # state every event (the previous bug) made every strategy effectively
        # stateless and never able to detect multi-event patterns.
        strategy_state: dict[str, Any] = {
            "sleeve_id": sleeve_id,
            "config_id": config_id,
            "config_hash": config_hash,
        }

        async for event in self._stream_events(range_start, range_end, overrides.market_filter):
            # 1) Drain any latency-deferred orders whose eta has passed.
            #    They submit against the book state AS OF NOW (post any
            #    book updates that happened between signal-time and eta).
            while pending and pending[0][0] <= event.ts:
                _eta, _order = heappop(pending)
                _book = books.get((_order.market_id, _order.asset_id))
                if _book is not None:
                    for _fill in await sim.submit(_order, _book):
                        fills_count += 1
                        _trade = tracker.on_fill(_fill, strategy_name, config_id, config_hash)
                        if _trade is not None:
                            trades_count += 1
                            try:
                                await db_writers.insert_trade(_trade, config_hash, source="replay")
                            except Exception:
                                logger.exception("failed to write replay trade")

            # 2) Maintain book state with this event
            self._apply_event_to_book(event, books)

            # 3) Tick simulator on_event for resting orders
            if event.market_id and event.asset_id:
                book = books.get((event.market_id, event.asset_id))
                if book is not None:
                    fills = await sim.on_event(event, book)
                    for fill in fills:
                        fills_count += 1
                        trade = tracker.on_fill(fill, strategy_name, config_id, config_hash)
                        if trade is not None:
                            trades_count += 1

            # 4) Dispatch event to strategy with PERSISTENT state
            try:
                signals: list[Signal] = await strategy.on_event(event, strategy_state)
            except Exception:
                logger.exception("strategy %s raised during replay event %s",
                                 strategy_name, event.event_id)
                continue

            for sig in signals:
                signals_count += 1
                # Apply size multiplier
                if overrides.size_multiplier != Decimal("1.0"):
                    sig = Signal(
                        signal_id=sig.signal_id,
                        sleeve_id=sleeve_id,           # rebind to replay sleeve
                        strategy_name=sig.strategy_name,
                        config_id=sig.config_id,
                        market_id=sig.market_id,
                        asset_id=sig.asset_id,
                        side=sig.side,
                        order_type=sig.order_type,
                        price=sig.price,
                        size=(sig.size * overrides.size_multiplier),
                        reason=sig.reason,
                        ts_signal=sig.ts_signal,
                        metadata=sig.metadata,
                    )
                else:
                    sig = Signal(
                        signal_id=sig.signal_id,
                        sleeve_id=sleeve_id,
                        strategy_name=sig.strategy_name,
                        config_id=sig.config_id,
                        market_id=sig.market_id,
                        asset_id=sig.asset_id,
                        side=sig.side,
                        order_type=sig.order_type,
                        price=sig.price,
                        size=sig.size,
                        reason=sig.reason,
                        ts_signal=sig.ts_signal,
                        metadata=sig.metadata,
                    )

                book = books.get((sig.market_id, sig.asset_id))
                if book is None:
                    continue

                eta = event.ts + latency_delay
                order = Order(
                    order_id=uuid4(),
                    signal_id=sig.signal_id,
                    sleeve_id=sleeve_id,
                    market_id=sig.market_id,
                    asset_id=sig.asset_id,
                    side=sig.side,
                    order_type=sig.order_type,
                    price=sig.price,
                    size=sig.size,
                    ts_signal=sig.ts_signal,
                    ts_placed=eta,
                )

                if latency_delay.total_seconds() <= 0:
                    # Zero-latency fast path — submit immediately.
                    fills = await sim.submit(order, book)
                    for fill in fills:
                        fills_count += 1
                        trade = tracker.on_fill(fill, strategy_name, config_id, config_hash)
                        if trade is not None:
                            trades_count += 1
                            try:
                                await db_writers.insert_trade(trade, config_hash, source="replay")
                            except Exception:
                                logger.exception("failed to write replay trade %s", trade.trade_id)
                else:
                    # Defer until book state has caught up to eta. Drained
                    # at the top of the next iteration whose event.ts >= eta.
                    heappush(pending, (eta, order))

        # Final drain — any orders still pending after the stream ends submit
        # against the last-known book state.
        while pending:
            _eta, _order = heappop(pending)
            _book = books.get((_order.market_id, _order.asset_id))
            if _book is None:
                continue
            for _fill in await sim.submit(_order, _book):
                fills_count += 1
                _trade = tracker.on_fill(_fill, strategy_name, config_id, config_hash)
                if _trade is not None:
                    trades_count += 1
                    try:
                        await db_writers.insert_trade(_trade, config_hash, source="replay")
                    except Exception:
                        pass

        # Compute summary metrics
        from src.analytics.metric_service import MetricService
        metric_svc = MetricService()
        # Metrics over replay's own trades — read back from DB by sleeve_id
        replay_trades = await self._fetch_trades_for_sleeve(sleeve_id)
        metrics = metric_svc.compute_all(replay_trades)

        pnl = tracker.pnl(sleeve_id)
        result = ReplayResult(
            run_id=run_id,
            strategy_name=strategy_name,
            config_id=config_id,
            config_hash=config_hash,
            range_start=range_start,
            range_end=range_end,
            signals=signals_count,
            fills=fills_count,
            trades=trades_count,
            realized_pnl=pnl.realized,
            metrics=metrics,
        )

        # Update run status
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE replay_runs
                    SET finished_at = now(),
                        status = 'completed',
                        summary = $1::jsonb
                    WHERE run_id = $2
                    """,
                    orjson.dumps({
                        "signals": signals_count,
                        "fills": fills_count,
                        "trades": trades_count,
                        "realized_pnl": str(pnl.realized),
                        "metrics": metrics,
                    }).decode(),
                    run_id,
                )
        except Exception:
            logger.exception("failed to mark replay %s complete", run_id)

        return result

    # ---------------------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------------------

    async def _stream_events(
        self,
        start: datetime,
        end: datetime,
        market_filter: list[str],
    ):
        """Async generator yielding MarketEvents from the DB in ts order."""
        try:
            pool = await get_pool()
        except RuntimeError:
            return

        # Stream in chunks via keyset pagination on (ts, id). Audit P1-2:
        # the previous version paginated by ``ts >= rows[-1].ts`` which
        # re-fetched the last row of every page (and could loop forever when
        # many events shared a timestamp). Tracking (ts, id) gives a strict
        # > predicate that's exact even for ts collisions.
        page = 10_000
        offset_ts = start
        offset_id: int = -1
        while True:
            async with pool.acquire() as conn:
                if market_filter:
                    rows = await conn.fetch(
                        """
                        SELECT id, event_id, event_type, market_id, asset_id, venue, ts, payload
                        FROM market_events
                        WHERE ts < $2
                          AND (ts > $1 OR (ts = $1 AND id > $4))
                          AND market_id = ANY($3)
                        ORDER BY ts ASC, id ASC
                        LIMIT $5
                        """,
                        offset_ts,
                        end,
                        market_filter,
                        offset_id,
                        page,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT id, event_id, event_type, market_id, asset_id, venue, ts, payload
                        FROM market_events
                        WHERE ts < $2
                          AND (ts > $1 OR (ts = $1 AND id > $3))
                        ORDER BY ts ASC, id ASC
                        LIMIT $4
                        """,
                        offset_ts,
                        end,
                        offset_id,
                        page,
                    )

            if not rows:
                return

            for r in rows:
                payload = r["payload"]
                if isinstance(payload, str):
                    try:
                        payload = orjson.loads(payload)
                    except Exception:
                        payload = {}
                yield MarketEvent(
                    event_id=r["event_id"] if isinstance(r["event_id"], UUID) else UUID(str(r["event_id"])),
                    event_type=EventType(r["event_type"]),
                    market_id=r["market_id"],
                    asset_id=r["asset_id"],
                    venue=r["venue"],
                    ts=r["ts"],
                    payload=payload or {},
                )

            offset_ts = rows[-1]["ts"]
            offset_id = int(rows[-1]["id"])
            if len(rows) < page:
                return

    def _apply_event_to_book(
        self,
        event: MarketEvent,
        books: dict[tuple[str, str], OrderBook],
    ) -> None:
        if event.market_id is None or event.asset_id is None:
            return
        key = (event.market_id, event.asset_id)

        if event.event_type == EventType.BOOK_SNAPSHOT:
            try:
                bids = [
                    PriceLevel(price=Decimal(str(b["price"])), size=Decimal(str(b["size"])))
                    for b in event.payload.get("bids", [])
                ]
                asks = [
                    PriceLevel(price=Decimal(str(a["price"])), size=Decimal(str(a["size"])))
                    for a in event.payload.get("asks", [])
                ]
            except Exception:
                return
            books[key] = OrderBook(
                market_id=event.market_id,
                asset_id=event.asset_id,
                bids=sorted(bids, key=lambda l: l.price, reverse=True),
                asks=sorted(asks, key=lambda l: l.price),
                last_update_ts=event.ts,
            )
        elif event.event_type == EventType.BOOK_DELTA:
            book = books.get(key)
            if book is None:
                return
            for ch in event.payload.get("changes", []):
                try:
                    side = Side.BUY if ch["side"] == "buy" else Side.SELL
                    price = Decimal(str(ch["price"]))
                    size = Decimal(str(ch["size"]))
                except (KeyError, ValueError):
                    continue
                levels = book.bids if side == Side.BUY else book.asks
                for i, lvl in enumerate(levels):
                    if lvl.price == price:
                        if size <= 0:
                            levels.pop(i)
                        else:
                            levels[i] = PriceLevel(price=price, size=size)
                        break
                else:
                    if size > 0:
                        levels.append(PriceLevel(price=price, size=size))
                if side == Side.BUY:
                    book.bids = sorted(levels, key=lambda l: l.price, reverse=True)
                else:
                    book.asks = sorted(levels, key=lambda l: l.price)
                book.last_update_ts = event.ts

    async def _fetch_trades_for_sleeve(self, sleeve_id: str):
        try:
            pool = await get_pool()
        except RuntimeError:
            return []
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
        from src.analytics.tag_service import _row_to_trade
        return [_row_to_trade(r) for r in rows]


def _overrides_to_json(o: ReplayOverrides) -> dict[str, Any]:
    return {
        "latency_ms": o.latency_ms,
        "size_multiplier": str(o.size_multiplier),
        "cancel_decay": str(o.cancel_decay) if o.cancel_decay is not None else None,
        "haircut_override": str(o.haircut_override) if o.haircut_override is not None else None,
        "market_filter": list(o.market_filter),
    }
