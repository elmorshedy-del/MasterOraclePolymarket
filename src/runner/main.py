"""Main async event loop.

Phase 1: full ingestion loop.

Boot sequence:
  1. Load configs (system + sleeves), discover plugins.
  2. Init DB pool, start EventWriter.
  3. Filter venues by ``pipes.yaml`` enable flags.
  4. Bootstrap Polymarket markets (the markets poller runs once before
     the CLOB subscribes, so the CLOB has an asset_id list to subscribe to).
  5. Start each enabled venue, multiplex its events into the bus.
  6. For each event: persist via EventWriter; orderbook store updated by the
     venue itself (CLOB does this); future phases will dispatch to strategies
     and the fill simulator from this same loop.
  7. Start periodic jobs: aggregator, retention.
  8. Run forever; gracefully shut down on SIGINT/SIGTERM.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from src.core import config as cfg
from src.core import plugin_loader
from src.core.events import MarketEvent
from src.core.interfaces import MarketDataSource
from src.db.connection import close_pool, get_pool
from src.db.event_writer import EventWriter
from src.runner.aggregator import Aggregator
from src.runner.retention import Retention

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

        self._tasks: list[asyncio.Task[Any]] = []
        self._stop = asyncio.Event()

        # Telemetry
        self.events_seen: int = 0

    async def start(self) -> None:
        # Configs ----------------------------------------------------------------
        self.system_cfg = cfg.load_system_config(REPO_ROOT / "src" / "configs" / "system")
        self.sleeves = cfg.load_sleeves(REPO_ROOT / "src" / "configs" / "sleeves")

        # Plugins ----------------------------------------------------------------
        plugins = plugin_loader.discover_all(REPO_ROOT)
        venue_plugins = [p for p in plugins if p.kind == "venue"]
        all_venues = {p.name: p.instance for p in venue_plugins}

        logger.info(
            "boot summary | runtime_hash=%s sleeves=%d venues=%d",
            self.system_cfg.config_hash,
            len(self.sleeves),
            len(venue_plugins),
        )

        # Filter venues by pipes.yaml -------------------------------------------
        pipes = self.system_cfg.pipes
        enable_map: dict[str, bool] = {
            "polymarket_clob": pipes.polymarket_clob,
            "polymarket_activity": pipes.polymarket_activity,
            "polymarket_markets": pipes.polymarket_clob,  # markets follows CLOB
            "news_rss": pipes.news_rss,
            "reddit": pipes.reddit,
            "kalshi": pipes.kalshi,
            "deribit": pipes.deribit,
            "binance_perp": pipes.binance_perp,
        }

        for name, venue in all_venues.items():
            should_enable = enable_map.get(name, False)
            venue.enabled = should_enable
            if should_enable:
                self.venues.append(venue)

        logger.info("enabled venues: %s", [v.name for v in self.venues])

        # DB ---------------------------------------------------------------------
        try:
            await get_pool()
        except RuntimeError as exc:
            logger.warning("DB pool not available (%s) — running without persistence", exc)

        await self.event_writer.start()

        # Bootstrap Polymarket asset list before the CLOB subscribes ------------
        markets_venue = next((v for v in self.venues if v.name == "polymarket_markets"), None)
        clob_venue = next((v for v in self.venues if v.name == "polymarket_clob"), None)
        if markets_venue and clob_venue:
            await markets_venue.start()
            # Trigger one immediate fetch so we have asset ids to subscribe to.
            try:
                # Pull markets synchronously by reading the venue's first poll.
                items = await asyncio.wait_for(markets_venue._fetch_markets(), timeout=30.0)  # noqa: SLF001
                for m in items:
                    markets_venue._known_meta[m.market_id] = m  # noqa: SLF001
            except Exception:  # noqa: BLE001
                logger.exception("[polymarket_markets] initial fetch failed; CLOB may have empty subscription")
            asset_ids = markets_venue.asset_ids()  # type: ignore[attr-defined]
            top_n = self.system_cfg.markets.top_n_by_volume
            asset_ids = asset_ids[:top_n]
            clob_venue.set_asset_ids(asset_ids)  # type: ignore[attr-defined]

        # Start remaining venues
        for v in self.venues:
            if v.name == "polymarket_markets":
                continue  # already started
            await v.start()

        # Periodic jobs ----------------------------------------------------------
        try:
            await self.aggregator.start()
            await self.retention.start()
        except Exception:  # noqa: BLE001
            logger.exception("failed to start periodic jobs (DB likely unavailable)")

        # Spawn one consumer task per venue --------------------------------------
        for v in self.venues:
            self._tasks.append(asyncio.create_task(self._consume(v), name=f"consume-{v.name}"))

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
        await self.event_writer.stop()
        await close_pool()

    async def run_forever(self) -> None:
        await self._stop.wait()

    async def _consume(self, venue: MarketDataSource) -> None:
        try:
            async for event in venue.stream_events():
                self.events_seen += 1
                self.event_writer.submit(event)
                # Phase 2 will dispatch to strategies and fill simulator here.
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("consumer for venue %s crashed", venue.name)


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
            # On Windows or restricted environments
            pass

    await stop_event.wait()
    logger.info("stopping runner...")
    await runner.stop()
    logger.info("runner stopped")


if __name__ == "__main__":
    asyncio.run(main())
