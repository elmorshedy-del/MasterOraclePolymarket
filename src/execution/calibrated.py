"""Tier 3 fill simulator — event replay + real-money calibration.

Off by default. Enabled via:
  - runtime.yaml: ``calibration.enabled: true``
  - Environment: ``CALIBRATION_WALLET_PRIVATE_KEY``, ``CALIBRATION_WALLET_ADDRESS``
  - Wallet must hold USDC on Polygon

When enabled, ``sample_rate`` % of paper orders are shadowed by tiny REAL
orders ($1–5) on Polymarket. Comparison data lives in ``calibration_trips``
table and informs per-market correction constants over time.

Phase 2 ships this as a stub that wraps EventReplayFillSimulator and emits
calibration trip records. The actual signing/submission of real orders is
gated behind the explicit feature flag and the user funding the wallet.
"""

from __future__ import annotations

import logging
import os
import random
from typing import Any

from src.core.config import CalibrationConfig, LatencyModel
from src.core.events import Fill, MarketEvent, Order, OrderBook
from src.execution.event_replay import EventReplayFillSimulator

logger = logging.getLogger(__name__)


class CalibratedFillSimulator:
    """Wraps EventReplayFillSimulator with optional real-order shadowing."""

    name: str = "calibrated"

    def __init__(
        self,
        latency: LatencyModel | None = None,
        calibration: CalibrationConfig | None = None,
    ) -> None:
        self._inner = EventReplayFillSimulator(latency=latency)
        self.calibration = calibration or CalibrationConfig()
        self._wallet_private_key = os.environ.get("CALIBRATION_WALLET_PRIVATE_KEY")
        self._wallet_address = os.environ.get("CALIBRATION_WALLET_ADDRESS")

        self.calibration_trips_attempted: int = 0
        self.calibration_trips_succeeded: int = 0

        if self.calibration.enabled and not (self._wallet_private_key and self._wallet_address):
            logger.warning(
                "calibrated fill sim enabled but wallet env vars missing; "
                "falling back to event_replay-only behavior"
            )
            self.calibration.enabled = False

    async def submit(self, order: Order, book: OrderBook) -> list[Fill]:
        fills = await self._inner.submit(order, book)

        if self.calibration.enabled and random.random() < self.calibration.sample_rate:
            # Phase 2: just log the intent. Real signing/submission is the
            # opt-in upgrade for when the user funds and wires the wallet.
            self.calibration_trips_attempted += 1
            logger.info(
                "[calibration] would shadow order %s (size %.4f, price %s) — STUB",
                order.order_id,
                float(order.size),
                order.price,
            )

        return fills

    async def on_event(self, event: MarketEvent, book: OrderBook) -> list[Fill]:
        return await self._inner.on_event(event, book)

    async def cancel(self, order_id: Any) -> None:
        await self._inner.cancel(order_id)

    def open_resting_count(self) -> int:
        return self._inner.open_resting_count()


def plugin() -> CalibratedFillSimulator:
    return CalibratedFillSimulator()
