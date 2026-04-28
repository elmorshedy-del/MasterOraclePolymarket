"""Auto-discovers plugins from filesystem and validates them against protocols.

Drop a file in any of the watched directories, the loader picks it up.

Watched paths:
  - src/venues/<name>.py             → MarketDataSource
  - src/execution/<name>.py          → FillSimulator
  - src/strategies/<name>/strategy.py → Strategy
  - src/analytics/tags/<name>.py     → Tag
  - src/analytics/metrics/<name>.py  → Metric

Each module must export a top-level callable named ``plugin`` that returns
the plugin instance, OR a class named ``Plugin`` that is instantiable
without arguments. The loader prefers ``plugin()`` if both are present.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.interfaces import (
    FillSimulator,
    MarketDataSource,
    Metric,
    Strategy,
    Tag,
)

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredPlugin:
    name: str
    kind: str                  # "venue" | "execution" | "strategy" | "tag" | "metric"
    module_path: Path
    instance: Any


# Map plugin kind → directory and protocol class
_REGISTRY: dict[str, tuple[Path, type]] = {
    "venue": (Path("src/venues"), MarketDataSource),
    "execution": (Path("src/execution"), FillSimulator),
    "strategy": (Path("src/strategies"), Strategy),
    "tag": (Path("src/analytics/tags"), Tag),
    "metric": (Path("src/analytics/metrics"), Metric),
}


def discover_all(repo_root: Path) -> list[DiscoveredPlugin]:
    """Walk all known plugin directories and return validated instances."""
    plugins: list[DiscoveredPlugin] = []
    for kind, (subpath, protocol) in _REGISTRY.items():
        plugins.extend(_discover_kind(repo_root / subpath, kind, protocol))
    return plugins


def _discover_kind(
    directory: Path,
    kind: str,
    protocol: type,
) -> Iterable[DiscoveredPlugin]:
    if not directory.exists():
        logger.warning("plugin directory missing: %s", directory)
        return []

    files = _candidate_files(directory, kind)
    found: list[DiscoveredPlugin] = []
    for module_path in files:
        try:
            instance = _load_module_plugin(module_path)
        except Exception as exc:  # noqa: BLE001 — surface but never crash boot
            logger.exception("failed to load %s plugin %s: %s", kind, module_path, exc)
            continue

        if instance is None:
            continue

        if not isinstance(instance, protocol):
            logger.error(
                "plugin %s does not implement %s — skipping",
                module_path,
                protocol.__name__,
            )
            continue

        name = getattr(instance, "name", module_path.stem)
        found.append(
            DiscoveredPlugin(
                name=name,
                kind=kind,
                module_path=module_path,
                instance=instance,
            )
        )
        logger.info("loaded %s plugin: %s", kind, name)

    return found


def _candidate_files(directory: Path, kind: str) -> list[Path]:
    """Strategies live in subfolders (strategies/<name>/strategy.py).

    Other plugins are flat files (tags/<name>.py).
    """
    if kind == "strategy":
        return [
            p
            for p in directory.rglob("strategy.py")
            if not _is_template_or_private(p)
        ]
    return [
        p
        for p in directory.glob("*.py")
        if not _is_template_or_private(p)
    ]


def _is_template_or_private(path: Path) -> bool:
    return any(part.startswith("_") for part in path.parts) or path.name == "__init__.py"


def _load_module_plugin(module_path: Path) -> Any | None:
    """Import the module and pull out its ``plugin()`` factory or ``Plugin`` class."""
    spec = importlib.util.spec_from_file_location(
        f"_plugin_{module_path.stem}",
        module_path,
    )
    if spec is None or spec.loader is None:
        logger.error("could not create spec for %s", module_path)
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if hasattr(module, "plugin") and callable(module.plugin):
        return module.plugin()

    if hasattr(module, "Plugin"):
        return module.Plugin()

    logger.warning(
        "%s defines no plugin() factory or Plugin class — skipping",
        module_path,
    )
    return None
