"""Per-sleeve strategy runtime.

Holds the loaded Strategy plugin + its sleeve config + per-sleeve state.
Receives MarketEvents from the runner; emits Signals to the order pipeline.

Mode awareness:
  - replay_only  → strategy is not invoked at all in live runner (Strategy Lab handles it)
  - live_log     → strategy invoked; signals logged; fill simulator NOT engaged
  - live_signal  → strategy + fill sim engaged; positions tracked but capital not committed
  - live_full    → full pipeline; capital committed; P&L tracked
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.core.config import LoadedSleeveConfig
from src.core.events import MarketEvent, RuntimeMode, Signal
from src.core.interfaces import Strategy

logger = logging.getLogger(__name__)


@dataclass
class StrategyRunner:
    sleeve: LoadedSleeveConfig
    strategy: Strategy
    state: dict[str, Any] = field(default_factory=dict)

    signals_emitted: int = 0
    last_event_ts: Any = None

    @property
    def mode(self) -> RuntimeMode:
        return self.sleeve.sleeve.mode

    @property
    def enabled(self) -> bool:
        return self.sleeve.sleeve.enabled

    async def on_event(self, event: MarketEvent) -> list[Signal]:
        if not self.enabled:
            return []
        if self.mode == RuntimeMode.REPLAY_ONLY:
            return []

        try:
            signals = await self.strategy.on_event(event, self.state)
        except Exception:  # noqa: BLE001
            logger.exception(
                "strategy %s/%s raised on event %s",
                self.strategy.name,
                self.sleeve.sleeve.config_id,
                event.event_id,
            )
            return []

        self.signals_emitted += len(signals)
        self.last_event_ts = event.ts
        return signals
