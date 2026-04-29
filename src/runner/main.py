"""Main async event loop.

Phase 3: tag application wired into the Trade-emission path.

Boot sequence (same as Phase 2 plus tag service init).
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.analytics.tag_service import TagService
from src.core import config as cfg
from src.core import plugin_loader
from src.core.events import (
    MarketEvent,
    Order,
    RuntimeMode,
    Signal,
)
from src.core.interfaces import FillSimulator, MarketDataSource
from src.db.connection import close_pool, get_pool
from src.db.event_writer import EventWriter
from src.db import writers as db_writers
from src.execution.calibrated import CalibratedFillSimulator
from src.execution.event_replay import EventReplayFillSimulator
from src.execution.pnl_snapshotter import PnLSnapshotter
from src.execution.position_tracker import PositionTracker
from src.execution.validation import FillValidator
from src.runner.aggregator import Aggregator
from src.runner.retention import Retention
from src.runner.strategy_runner import StrategyRunner
from src.venues._orderbook_store import STORE

logger = logging.getLogger(__name__)


REPO_ROOT = Path(__file__).resolve().parents[2]


class Runner:
    def __init__(self) -> None:
        self.system_cfg: cfg.LoadedSystemConfig | None = None
        self.sleeves: list[cfg.LoadedSleeveConfig] = []

        self.venues: list[MarketDataSource] = []
        self.event_writer = EventWriter()
        self.aggregator = Aggregator()
        self.retention = Retention()
        self.fill_validator = FillValidator()

        self.fill_simulator: FillSimulator | None = None
        self.position_tracker: PositionTracker | None = None
        self.pnl_snapshotter: PnLSnapshotter | None = None
        self.tag_service: TagService | None = None
        self.strategy_runners: list[StrategyRunner] = []

        self._tasks: list[asyncio.Task[Any]] = []
        self._stop = asyncio.Event()
        self._db_available: bool = False

        self.events_seen: int = 0
        self.signals_emitted: int = 0
        self.fills_simulated: int = 0
        self.trades_emitted: int = 0

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def start(self) -> None:
        await self._load_configs_and_plugins()
        await self._init_db_layer()
        await self._init_execution_layer()
        await self._init_strategy_layer()
        await self._init_venues()
        await self._start_periodic_jobs()
        self._spawn_consumers()

    async def stop(self) -> None:
        self._stop.set()

        for v in self.venues:
            try:
                await v.stop()
            except Exception:  # noqa: BLE001
                logger.exception("venue %s stop failed", v.name)

        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

        await self.aggregator.stop()
        await self.retention.stop()
        await self.fill_validator.stop()
        if self.pnl_snapshotter is not None:
            await self.pnl_snapshotter.stop()
        await self.event_writer.stop()
        await close_pool()

    async def run_forever(self) -> None:
        await self._stop.wait()

    # -----------------------------------------------------------------------
    # Init steps
    # -----------------------------------------------------------------------

    async def _load_configs_and_plugins(self) -> None:
        self.system_cfg = cfg.load_system_config(REPO_ROOT / "src" / "configs" / "system")
        self.sleeves = cfg.load_sleeves(REPO_ROOT / "src" / "configs" / "sleeves")

        self._plugins = plugin_loader.discover_all(REPO_ROOT)
        self._venue_plugins = {p.name: p.instance for p in self._plugins if p.kind == "venue"}
        self._strategy_plugins = {p.name: p.instance for p in self._plugins if p.kind == "strategy"}
        self.tag_service = TagService()

        logger.info(
            "boot summary | runtime_hash=%s sleeves=%d venues=%d strategies=%d tags=%d",
            self.system_cfg.config_hash,
            len(self.sleeves),
            len(self._venue_plugins),
            len(self._strategy_plugins),
            len(self.tag_service.tag_names),
        )

    async def _init_db_layer(self) -> None:
        try:
            await get_pool()
            self._db_available = True
        except RuntimeError as exc:
            logger.warning("DB pool not available (%s) — running without persistence", exc)
            self._db_available = False

        await self.event_writer.start()

    async def _init_execution_layer(self) -> None:
        assert self.system_cfg is not None

        sim_name = self.system_cfg.runtime.fill_simulator
        if sim_name == "calibrated":
            self.fill_simulator = CalibratedFillSimulator(
                latency=self.system_cfg.runtime.latency,
                calibration=self.system_cfg.runtime.calibration,
            )
        else:
            self.fill_simulator = EventReplayFillSimulator(
                latency=self.system_cfg.runtime.latency,
            )
        logger.info("fill simulator: %s", self.fill_simulator.name)

        edge_class_by_sleeve = {
            ls.sleeve.sleeve_id: ls.sleeve.edge_class or ""
            for ls in self.sleeves
        }
        starting_capital = {
            ls.sleeve.sleeve_id: ls.sleeve.starting_capital_usd
            for ls in self.sleeves
        }
        self.position_tracker = PositionTracker(
            sleeve_starting_capital=starting_capital,
            haircut=self.system_cfg.runtime.haircut,
            edge_class_by_sleeve={k: v for k, v in edge_class_by_sleeve.items() if v},
        )

        if self._db_available:
            self.pnl_snapshotter = PnLSnapshotter(self.position_tracker)
        else:
            self.pnl_snapshotter = None

    async def _init_strategy_layer(self) -> None:
        for loaded_sleeve in self.sleeves:
            if not loaded_sleeve.sleeve.enabled:
                continue
            strategy_name = loaded_sleeve.sleeve.strategy
            strategy = self._strategy_plugins.get(strategy_name)
            if strategy is None:
                logger.warning(
                    "sleeve %s references unknown strategy %s — skipping",
                    loaded_sleeve.sleeve.sleeve_id,
                    strategy_name,
                )
                continue
            self.strategy_runners.append(
                StrategyRunner(sleeve=loaded_sleeve, strategy=strategy)
            )

            if self._db_available:
                try:
                    await db_writers.upsert_sleeve(
                        sleeve_id=loaded_sleeve.sleeve.sleeve_id,
                        strategy_name=strategy_name,
                        config_id=loaded_sleeve.sleeve.config_id,
                        edge_class=loaded_sleeve.sleeve.edge_class,
                        starting_capital_usd=float(loaded_sleeve.sleeve.starting_capital_usd),
                        mode=loaded_sleeve.sleeve.mode.value,
                        enabled=loaded_sleeve.sleeve.enabled,
                        config_hash=loaded_sleeve.config_hash,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("failed to upsert sleeve %s", loaded_sleeve.sleeve.sleeve_id)

        logger.info("strategy runners: %d active", len(self.strategy_runners))

    async def _init_venues(self) -> None:
        assert self.system_cfg is not None
        pipes = self.system_cfg.pipes
        enable_map: dict[str, bool] = {
            "polymarket_clob": pipes.polymarket_clob,
            "polymarket_activity": pipes.polymarket_activity,
            "polymarket_markets": pipes.polymarket_clob,
            "news_rss": pipes.news_rss,
            "reddit": pipes.reddit,
            "kalshi": pipes.kalshi,
            "deribit": pipes.deribit,
            "binance_perp": pipes.binance_perp,
        }

        for name, venue in self._venue_plugins.items():
            should_enable = enable_map.get(name, False)
            venue.enabled = should_enable
            if should_enable:
                self.venues.append(venue)

        logger.info("enabled venues: %s", [v.name for v in self.venues])

        markets_venue = next((v for v in self.venues if v.name == "polymarket_markets"), None)
        clob_venue = next((v for v in self.venues if v.name == "polymarket_clob"), None)
        if markets_venue and clob_venue:
            await markets_venue.start()
            try:
                items = await asyncio.wait_for(markets_venue._fetch_markets(), timeout=30.0)  # noqa: SLF001
                for m in items:
                    markets_venue._known_meta[m.market_id] = m  # noqa: SLF001
            except Exception:  # noqa: BLE001
                logger.exception("[polymarket_markets] initial fetch failed")
            asset_ids = markets_venue.asset_ids()  # type: ignore[attr-defined]
            top_n = self.system_cfg.markets.top_n_by_volume
            asset_ids = asset_ids[:top_n]
            clob_venue.set_asset_ids(asset_ids)  # type: ignore[attr-defined]

        for v in self.venues:
            if v.name == "polymarket_markets":
                continue
            await v.start()

    async def _start_periodic_jobs(self) -> None:
        if not self._db_available:
            return
        try:
            await self.aggregator.start()
            await self.retention.start()
            await self.fill_validator.start()
            if self.pnl_snapshotter is not None:
                await self.pnl_snapshotter.start()
        except Exception:  # noqa: BLE001
            logger.exception("failed to start periodic jobs")

    def _spawn_consumers(self) -> None:
        for v in self.venues:
            self._tasks.append(asyncio.create_task(self._consume(v), name=f"consume-{v.name}"))

    # -----------------------------------------------------------------------
    # Hot path
    # -----------------------------------------------------------------------

    async def _consume(self, venue: MarketDataSource) -> None:
        try:
            async for event in venue.stream_events():
                await self._on_event(event)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("consumer for venue %s crashed", venue.name)

    async def _on_event(self, event: MarketEvent) -> None:
        self.events_seen += 1
        self.event_writer.submit(event)
        await self._tick_fill_simulator(event)

        for runner in self.strategy_runners:
            signals = await runner.on_event(event)
            for sig in signals:
                self.signals_emitted += 1
                await self._handle_signal(sig, runner)

    async def _tick_fill_simulator(self, event: MarketEvent) -> None:
        if self.fill_simulator is None or self.position_tracker is None:
            return
        if event.market_id is None or event.asset_id is None:
            return
        book = STORE.get(event.market_id, event.asset_id)
        if book is None:
            return
        try:
            fills = await self.fill_simulator.on_event(event, book)
        except Exception:  # noqa: BLE001
            logger.exception("fill_simulator.on_event raised for event %s", event.event_id)
            return
        for fill in fills:
            await self._handle_fill(fill)

    async def _handle_signal(self, signal: Signal, runner: StrategyRunner) -> None:
        if self._db_available:
            try:
                await db_writers.insert_signal(signal)
            except Exception:  # noqa: BLE001
                logger.exception("failed to persist signal %s", signal.signal_id)

        if runner.mode == RuntimeMode.LIVE_LOG:
            return

        if self.fill_simulator is None or self.position_tracker is None:
            return

        book = STORE.get(signal.market_id, signal.asset_id)
        if book is None:
            return

        from src.execution._latency import apply_latency
        assert self.system_cfg is not None
        await apply_latency(self.system_cfg.runtime.latency)

        ts_placed = datetime.now(tz=timezone.utc)
        order = Order(
            order_id=uuid4(),
            signal_id=signal.signal_id,
            sleeve_id=signal.sleeve_id,
            market_id=signal.market_id,
            asset_id=signal.asset_id,
            side=signal.side,
            order_type=signal.order_type,
            price=signal.price,
            size=signal.size,
            ts_signal=signal.ts_signal,
            ts_placed=ts_placed,
            metadata={"strategy": runner.strategy.name, "config": runner.sleeve.sleeve.config_id},
        )

        if self._db_available:
            try:
                await db_writers.insert_order(order)
            except Exception:  # noqa: BLE001
                logger.exception("failed to persist order %s", order.order_id)

        book = STORE.get(signal.market_id, signal.asset_id) or book

        try:
            fills = await self.fill_simulator.submit(order, book)
        except Exception:  # noqa: BLE001
            logger.exception("fill_simulator.submit raised for order %s", order.order_id)
            return

        for fill in fills:
            await self._handle_fill(fill, runner=runner)

    async def _handle_fill(
        self,
        fill,
        runner: StrategyRunner | None = None,
    ) -> None:
        self.fills_simulated += 1

        if self._db_available:
            try:
                await db_writers.insert_fill(fill)
            except Exception:  # noqa: BLE001
                logger.exception("failed to persist fill %s", fill.fill_id)

        if runner is not None and runner.mode == RuntimeMode.LIVE_SIGNAL:
            return

        if self.position_tracker is None:
            return

        if runner is None:
            runner = self._runner_for_sleeve(fill.sleeve_id)

        if runner is None:
            return

        trade = self.position_tracker.on_fill(
            fill,
            strategy_name=runner.strategy.name,
            config_id=runner.sleeve.sleeve.config_id,
            config_hash=runner.sleeve.config_hash,
        )
        if trade is None:
            return

        self.trades_emitted += 1

        if self._db_available:
            try:
                await db_writers.insert_trade(trade, runner.sleeve.config_hash)
            except Exception:  # noqa: BLE001
                logger.exception("failed to persist trade %s", trade.trade_id)

            # Apply tags + persist to denormalized columns + tags_extra
            if self.tag_service is not None:
                try:
                    await self.tag_service.tag_and_persist(trade)
                except Exception:  # noqa: BLE001
                    logger.exception("tag_and_persist failed for trade %s", trade.trade_id)

    def _runner_for_sleeve(self, sleeve_id: str) -> StrategyRunner | None:
        for r in self.strategy_runners:
            if r.sleeve.sleeve.sleeve_id == sleeve_id:
                return r
        return None


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    runner = Runner()
    await runner.start()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _on_signal():
        logger.info("shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            pass

    await stop_event.wait()
    logger.info("stopping runner...")
    await runner.stop()
    logger.info("runner stopped")


if __name__ == "__main__":
    asyncio.run(main())
