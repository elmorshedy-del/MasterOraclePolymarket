"""YAML configuration with hot reload.

Two layers:
  1. System config (src/configs/system/*.yaml) — runtime, pipes, markets
  2. Sleeve configs (src/configs/sleeves/*.yaml) — one file per sleeve

The runner mounts a watcher over both directories. On change, the affected
config is re-parsed and a ConfigChange event is fired so the relevant
component (a strategy runner, a venue, the global runtime) can react
without restart.

Every config change is meant to be a git commit; the loader records
``config_hash`` (a SHA-256 of the canonical YAML) so each Trade can be
attributed to a specific config version.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from watchfiles import awatch

from src.core.events import RuntimeMode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System config models
# ---------------------------------------------------------------------------


class LatencyModel(BaseModel):
    """Latency injection parameters. System constant — see DESIGN.md §5."""

    decision_ms: int = 250
    code_path_ms: int = 250
    network_buffer_ms: int = 1000

    def total_ms(self) -> int:
        return self.decision_ms + self.code_path_ms + self.network_buffer_ms


class HaircutConfig(BaseModel):
    """Realism haircut configuration — see DESIGN.md §3."""

    default: Decimal = Decimal("0.22")
    overrides_by_edge_class: dict[str, Decimal] = Field(
        default_factory=lambda: {
            "pure_arb": Decimal("0.18"),
            "maker": Decimal("0.38"),
            "latency_sensitive": Decimal("0.28"),
            "slow": Decimal("0.15"),
        }
    )


class CalibrationConfig(BaseModel):
    """Tier 3 calibration — off by default."""

    enabled: bool = False
    sample_rate: float = 0.0           # fraction of paper orders shadowed by real orders
    wallet_address: str | None = None
    max_real_size_usd: Decimal = Decimal("5")


class RuntimeConfig(BaseModel):
    latency: LatencyModel = Field(default_factory=LatencyModel)
    haircut: HaircutConfig = Field(default_factory=HaircutConfig)
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)
    fill_simulator: str = "event_replay"
    realism_haircut_display: bool = True   # apply haircut to dashboard headline P&L


class PipesConfig(BaseModel):
    """Per-pipe enable flags."""

    polymarket_clob: bool = True
    polymarket_activity: bool = True
    news_rss: bool = True
    reddit: bool = False
    kalshi: bool = False
    deribit: bool = False
    binance_perp: bool = False


class MarketsConfig(BaseModel):
    """Which markets to subscribe to."""

    top_n_by_volume: int = 1000
    always_on_categories: list[str] = Field(default_factory=lambda: ["weather", "politics"])
    always_on_market_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Sleeve config model
# ---------------------------------------------------------------------------


class SleeveConfig(BaseModel):
    """One sleeve = (strategy + named config + capital).

    All scalar fields are hot-reloadable.
    """

    sleeve_id: str
    strategy: str                      # strategy name (folder under src/strategies/)
    config_id: str                     # human label e.g. "default", "aggressive"
    enabled: bool = True
    mode: RuntimeMode = RuntimeMode.REPLAY_ONLY
    starting_capital_usd: Decimal = Decimal("5000")
    edge_class: str | None = None      # if None, falls back to strategy.edge_class

    # Strategy parameters — strategy-specific schema validated by the strategy itself
    params: dict[str, Any] = Field(default_factory=dict)

    # Common policy fields
    market_filter: dict[str, Any] = Field(default_factory=dict)
    max_concurrent_positions: int = 25
    max_exposure_per_market_usd: Decimal = Decimal("500")
    loss_management: str = "none"      # "none" | "stop_-30" | "stop_-50"


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


@dataclass
class LoadedSystemConfig:
    runtime: RuntimeConfig
    pipes: PipesConfig
    markets: MarketsConfig
    config_hash: str
    loaded_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


@dataclass
class LoadedSleeveConfig:
    sleeve: SleeveConfig
    config_hash: str
    source_path: Path
    loaded_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


def _hash_yaml(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_system_config(system_dir: Path) -> LoadedSystemConfig:
    runtime_path = system_dir / "runtime.yaml"
    pipes_path = system_dir / "pipes.yaml"
    markets_path = system_dir / "markets.yaml"

    runtime_text = runtime_path.read_text() if runtime_path.exists() else ""
    pipes_text = pipes_path.read_text() if pipes_path.exists() else ""
    markets_text = markets_path.read_text() if markets_path.exists() else ""

    runtime = RuntimeConfig(**(yaml.safe_load(runtime_text) or {}))
    pipes = PipesConfig(**(yaml.safe_load(pipes_text) or {}))
    markets = MarketsConfig(**(yaml.safe_load(markets_text) or {}))

    return LoadedSystemConfig(
        runtime=runtime,
        pipes=pipes,
        markets=markets,
        config_hash=_hash_yaml(runtime_text + pipes_text + markets_text),
    )


def load_sleeves(sleeves_dir: Path) -> list[LoadedSleeveConfig]:
    if not sleeves_dir.exists():
        return []

    out: list[LoadedSleeveConfig] = []
    for path in sorted(sleeves_dir.glob("*.yaml")):
        text = path.read_text()
        try:
            data = yaml.safe_load(text) or {}
            sleeve = SleeveConfig(**data)
        except Exception as exc:  # noqa: BLE001
            logger.exception("invalid sleeve config %s: %s", path, exc)
            continue
        out.append(
            LoadedSleeveConfig(
                sleeve=sleeve,
                config_hash=_hash_yaml(text),
                source_path=path,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Hot reload
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigChange:
    path: Path
    kind: str                          # "system" | "sleeve"


async def watch_configs(
    system_dir: Path,
    sleeves_dir: Path,
    on_change: Callable[[ConfigChange], None] | None = None,
) -> AsyncIterator[ConfigChange]:
    """Async iterator of config-change events.

    Caller is responsible for reloading the affected config and propagating.
    The optional ``on_change`` callback fires for each event in addition to
    the iterator yield (useful for fire-and-forget hooks).
    """

    async for changes in awatch(system_dir, sleeves_dir):
        for _change_type, raw_path in changes:
            path = Path(raw_path)
            kind = "system" if system_dir in path.parents else "sleeve"
            ev = ConfigChange(path=path, kind=kind)
            if on_change:
                try:
                    on_change(ev)
                except Exception:  # noqa: BLE001
                    logger.exception("config on_change handler failed for %s", path)
            yield ev
