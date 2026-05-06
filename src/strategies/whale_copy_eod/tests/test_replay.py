"""Replay smoke for whale_copy_eod. Skips when DATABASE_URL unset."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.runner.replay_engine import ReplayEngine, ReplayOverrides

pytestmark = pytest.mark.asyncio


async def test_replay_smoke():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("no DATABASE_URL")
    end = datetime.now(tz=UTC)
    engine = ReplayEngine()
    result = await engine.run(
        strategy_name="whale_copy_eod",
        config_id="default",
        range_start=end - timedelta(days=14),
        range_end=end,
        starting_capital=Decimal("5000"),
        edge_class="copy",
        overrides=ReplayOverrides(),
    )
    assert result is not None
