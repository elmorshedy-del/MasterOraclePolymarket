"""Replay-engine override math tests — pure-function / dataclass shape only.

Full event-stream replay is exercised in tests/integration; here we just
ensure that ReplayOverrides + the latency-distribution math do not regress.
"""

from __future__ import annotations

from decimal import Decimal

from src.core.config import LatencyModel
from src.runner.replay_engine import ReplayOverrides


def test_overrides_defaults():
    o = ReplayOverrides()
    assert o.latency_ms is None
    assert o.size_multiplier == Decimal("1.0")
    assert o.cancel_decay is None
    assert o.haircut_override is None
    assert o.market_filter == []


def test_latency_distribution_thirds():
    """The replay engine distributes latency_ms evenly across the 3 segments."""
    # We don't run the engine here — just exercise the math the same way.
    latency_ms = 300
    third = latency_ms // 3
    model = LatencyModel(
        decision_ms=third,
        code_path_ms=third,
        network_buffer_ms=latency_ms - 2 * third,
    )
    assert model.total_ms() == 300
    assert model.decision_ms == 100
    assert model.code_path_ms == 100
    assert model.network_buffer_ms == 100


def test_latency_distribution_uneven_remainder_in_network():
    latency_ms = 100
    third = latency_ms // 3   # 33
    model = LatencyModel(
        decision_ms=third,
        code_path_ms=third,
        network_buffer_ms=latency_ms - 2 * third,
    )
    assert model.total_ms() == 100
    assert model.network_buffer_ms == 34


def test_size_multiplier_applies_to_decimal():
    o = ReplayOverrides(size_multiplier=Decimal("2.5"))
    base = Decimal("10")
    assert (base * o.size_multiplier) == Decimal("25.0")
