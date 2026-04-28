"""Main async event loop.

Phase 0: stub only. Phase 1 fleshes out ingestion + dispatch.

The runner is a single asyncio process that:
  1. Loads system config + sleeves
  2. Discovers and starts enabled MarketDataSource plugins (venues)
  3. Discovers Strategy plugins, instantiates one runner per enabled sleeve
  4. Discovers FillSimulator (chosen by runtime.yaml)
  5. Multiplexes events from all sources into a single bus
  6. For each event:
       - update in-memory order book if it's a CLOB event
       - forward to subscribed strategies (per their required_event_types)
       - forward to fill simulator (for resting maker order processing)
  7. For each Signal: convert to Order with latency injection, submit to fill sim
  8. For each Fill: persist; update positions; on close, emit Trade with tags
  9. Watch config files; reload on change
 10. Run periodic jobs (P&L snapshots, retention, redemption sweep)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from src.core import config as cfg
from src.core import plugin_loader

logger = logging.getLogger(__name__)


REPO_ROOT = Path(__file__).resolve().parents[2]


async def main() -> None:
    """Boot the platform.

    Phase 0: just discover plugins and load config to verify wiring.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    system_cfg = cfg.load_system_config(REPO_ROOT / "src" / "configs" / "system")
    sleeves = cfg.load_sleeves(REPO_ROOT / "src" / "configs" / "sleeves")
    plugins = plugin_loader.discover_all(REPO_ROOT)

    logger.info(
        "boot summary | runtime_hash=%s sleeves=%d plugins=%d (venues=%d, exec=%d, strategies=%d, tags=%d, metrics=%d)",
        system_cfg.config_hash,
        len(sleeves),
        len(plugins),
        sum(1 for p in plugins if p.kind == "venue"),
        sum(1 for p in plugins if p.kind == "execution"),
        sum(1 for p in plugins if p.kind == "strategy"),
        sum(1 for p in plugins if p.kind == "tag"),
        sum(1 for p in plugins if p.kind == "metric"),
    )

    logger.info("Phase 0 boot complete. Phase 1 will start the event loop here.")


if __name__ == "__main__":
    asyncio.run(main())
