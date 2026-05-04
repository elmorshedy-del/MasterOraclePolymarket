"""Phase 6: every new strategy is discovered + every sleeve YAML parses."""

from __future__ import annotations

from pathlib import Path

from src.core import config as cfg
from src.core import plugin_loader

REPO_ROOT = Path(__file__).resolve().parents[2]


PHASE6_STRATEGIES = (
    ("whale_copy_eod",          "copy"),
    ("mean_revert_post_spike",  "directional"),
    ("momentum_orderbook",      "latency_sensitive"),
)


def test_phase6_strategies_discovered():
    plugins = plugin_loader.discover_all(REPO_ROOT)
    by_name = {(p.kind, p.name): p.instance for p in plugins}
    for name, edge_class in PHASE6_STRATEGIES:
        inst = by_name.get(("strategy", name))
        assert inst is not None, f"plugin loader did not pick up {name}"
        assert inst.edge_class == edge_class


def test_phase6_default_sleeves_parse():
    sleeves = cfg.load_sleeves(REPO_ROOT / "src" / "configs" / "sleeves")
    sleeve_ids = {s.sleeve.sleeve_id for s in sleeves}
    for name, _ in PHASE6_STRATEGIES:
        assert f"{name}__default" in sleeve_ids


def test_copy_haircut_class_is_present():
    """Phase 6 introduces edge_class 'copy'. Verify it's wired into the
    default haircut config."""
    from decimal import Decimal

    from src.core.config import HaircutConfig

    h = HaircutConfig()
    assert "copy" in h.overrides_by_edge_class
    assert h.overrides_by_edge_class["copy"] == Decimal("0.20")
    # 'tail' was implicit before; now explicit
    assert "tail" in h.overrides_by_edge_class
