"""Verify the cross_outcome_arb plugin is discovered by the loader and that
its sleeve YAMLs parse cleanly.

This guards the strategy-onboarding contract: dropping the folder + sleeve
YAML is enough to register the sleeve, no central registry to update.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from src.core import config as cfg
from src.core import plugin_loader

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_plugin_loader_discovers_cross_outcome_arb():
    plugins = plugin_loader.discover_all(REPO_ROOT)
    by_name = {(p.kind, p.name): p for p in plugins}
    assert ("strategy", "cross_outcome_arb") in by_name

    inst = by_name[("strategy", "cross_outcome_arb")].instance
    assert inst.edge_class == "pure_arb"
    assert "polymarket_clob" in inst.required_data_sources()


def test_default_sleeve_config_loads():
    sleeves = cfg.load_sleeves(REPO_ROOT / "src" / "configs" / "sleeves")
    sleeve_ids = {s.sleeve.sleeve_id for s in sleeves}
    assert "cross_outcome_arb__default" in sleeve_ids

    default = next(s for s in sleeves if s.sleeve.sleeve_id == "cross_outcome_arb__default")
    assert default.sleeve.strategy == "cross_outcome_arb"
    assert default.sleeve.edge_class == "pure_arb"
    assert default.sleeve.starting_capital_usd == Decimal("5000")


def test_aggressive_and_conservative_configs_exist():
    sleeves = cfg.load_sleeves(REPO_ROOT / "src" / "configs" / "sleeves")
    sleeve_ids = {s.sleeve.sleeve_id for s in sleeves}
    assert "cross_outcome_arb__aggressive" in sleeve_ids
    assert "cross_outcome_arb__conservative" in sleeve_ids
