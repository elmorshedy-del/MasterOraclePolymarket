"""Regression tests for the audit-driven fixes.

These guard the architectural P0s called out in the audit so they don't
silently regress as new strategies / sleeves land.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from src.core import config as cfg
from src.core import plugin_loader
from src.core.events import RuntimeMode
from src.runner.main import _instantiate_with_params
from src.runner.strategy_runner import StrategyRunner

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Plugin loader — unique module names + sys.modules registration
# ---------------------------------------------------------------------------


def test_plugin_loader_uses_unique_module_names_per_path():
    """Two strategies sharing 'strategy.py' must not collide in sys.modules."""
    import sys

    plugins = plugin_loader.discover_all(REPO_ROOT)
    strategy_plugins = [p for p in plugins if p.kind == "strategy"]
    # All strategy module names should now begin with the per-path prefix.
    seen_names: set[str] = set()
    for sp in strategy_plugins:
        # The plugin loader names modules like _plugin.src.strategies.<name>.strategy
        prefix = f"_plugin.src.strategies.{sp.name}.strategy"
        # Allow normalized variants (e.g. .py stripped) — at minimum no two
        # plugins should share a module name.
        for name in list(sys.modules.keys()):
            if name.endswith(f".{sp.name}.strategy") or name == prefix:
                seen_names.add(name)

    # No collisions = number of registered plugin modules >= number of
    # discovered strategies (some may be aliased, which is fine).
    assert len(seen_names) >= len(strategy_plugins)


# ---------------------------------------------------------------------------
# Per-sleeve instantiation — sleeve YAML params reach the strategy
# ---------------------------------------------------------------------------


def test_per_sleeve_strategy_instantiation_applies_params():
    """A sleeve YAML's params: must reach the strategy instance."""
    plugins = plugin_loader.discover_all(REPO_ROOT)
    template = next(
        p.instance for p in plugins
        if p.kind == "strategy" and p.name == "cross_outcome_arb"
    )

    # Default-constructed: min_edge_bps = 100
    default = type(template)()
    assert default.params.min_edge_bps == 100

    # Sleeve-style construction: min_edge_bps = 50
    aggressive = _instantiate_with_params(template, {"min_edge_bps": 50})
    assert aggressive.params.min_edge_bps == 50

    # Decimal field passes through string YAML values
    custom = _instantiate_with_params(template, {"max_sum_threshold": "0.995"})
    assert custom.params.max_sum_threshold == Decimal("0.995")


def test_unknown_param_falls_back_without_crash():
    """Unknown kwargs in YAML must not crash boot."""
    plugins = plugin_loader.discover_all(REPO_ROOT)
    template = next(
        p.instance for p in plugins
        if p.kind == "strategy" and p.name == "cross_outcome_arb"
    )
    # Strategies use a kwarg whitelist, so they happily accept unknown keys.
    # The fallback path is exercised when a strategy raises TypeError. We test
    # that the runner doesn't crash either way.
    inst = _instantiate_with_params(template, {"definitely_not_a_param": 99})
    assert inst is not None
    assert inst.name == "cross_outcome_arb"


# ---------------------------------------------------------------------------
# StrategyRunner pre-populates sleeve identity into state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_state_is_seeded_with_sleeve_identity():
    """Strategies read state['sleeve_id'] when constructing Signals — runner
    must seed that BEFORE the first event."""
    sleeves = cfg.load_sleeves(REPO_ROOT / "src" / "configs" / "sleeves")
    sleeve = next(s for s in sleeves if s.sleeve.sleeve_id == "cross_outcome_arb__default")

    plugins = plugin_loader.discover_all(REPO_ROOT)
    template = next(
        p.instance for p in plugins
        if p.kind == "strategy" and p.name == "cross_outcome_arb"
    )
    strat = _instantiate_with_params(template, sleeve.sleeve.params)
    sleeve_with_mode = sleeve
    object.__setattr__(sleeve_with_mode.sleeve, "mode", RuntimeMode.LIVE_FULL)

    runner = StrategyRunner(sleeve=sleeve_with_mode, strategy=strat)
    assert runner.state["sleeve_id"] == "cross_outcome_arb__default"
    assert runner.state["config_id"] == "default"
    assert runner.state["config_hash"] == sleeve.config_hash


# ---------------------------------------------------------------------------
# Haircut config covers every edge_class used by shipped strategies
# ---------------------------------------------------------------------------


def test_haircut_covers_all_strategy_edge_classes():
    plugins = plugin_loader.discover_all(REPO_ROOT)
    edge_classes = {
        getattr(p.instance, "edge_class", None)
        for p in plugins if p.kind == "strategy"
    }
    edge_classes.discard(None)
    overrides = cfg.HaircutConfig().overrides_by_edge_class
    missing = edge_classes - set(overrides.keys())
    assert missing == set(), (
        f"strategies declare edge classes {missing} that have no haircut "
        f"override — they would silently fall through to the platform default"
    )
