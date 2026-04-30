"""Phase 5: every new strategy is discovered + every sleeve YAML parses."""

from __future__ import annotations

from pathlib import Path

from src.core import config as cfg
from src.core import plugin_loader

REPO_ROOT = Path(__file__).resolve().parents[2]


PHASE5_STRATEGIES = (
    ("basket_arb",         "pure_arb"),
    ("redemption_sniper",  "slow"),
    ("weather_tail_sell",  "tail"),
    ("weather_tail_buy",   "tail"),
    ("maker_passive",      "maker"),
)


def test_phase5_strategies_discovered():
    plugins = plugin_loader.discover_all(REPO_ROOT)
    by_name = {(p.kind, p.name): p.instance for p in plugins}
    for name, edge_class in PHASE5_STRATEGIES:
        inst = by_name.get(("strategy", name))
        assert inst is not None, f"plugin loader did not pick up {name}"
        assert inst.edge_class == edge_class


def test_phase5_default_sleeves_parse():
    sleeves = cfg.load_sleeves(REPO_ROOT / "src" / "configs" / "sleeves")
    sleeve_ids = {s.sleeve.sleeve_id for s in sleeves}
    for name, _ in PHASE5_STRATEGIES:
        assert f"{name}__default" in sleeve_ids


def test_market_meta_event_type_exists():
    from src.core.events import EventType
    assert EventType.MARKET_META.value == "market_meta"
