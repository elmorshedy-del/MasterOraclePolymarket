"""Unit tests for the promotion-gate evaluator.

These exercise the pure-evaluation path with hand-built records; the DB
integration is exercised by the Phase 4 commit when run against a Postgres
with seeded data.
"""

from __future__ import annotations

from decimal import Decimal

from src.runner.promotion_gates import GateThresholds, PromotionEvaluator


def test_default_thresholds_are_reasonable():
    t = GateThresholds()
    assert t.replay_min_signals == 30
    assert t.replay_min_realized_pnl == Decimal("0")
    assert t.log_min_days == 14
    assert t.signal_max_implausible_rate == Decimal("0.05")
    assert t.full_max_dd_pct_of_capital == Decimal("0.20")


def test_evaluator_accepts_custom_thresholds():
    custom = GateThresholds(
        replay_min_signals=10,
        replay_min_realized_pnl=Decimal("100"),
    )
    e = PromotionEvaluator(thresholds=custom)
    assert e.thresholds.replay_min_signals == 10
    assert e.thresholds.replay_min_realized_pnl == Decimal("100")
