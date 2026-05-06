"""Replay validation for basket_arb. Skips when DATABASE_URL unset."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.runner.replay_engine import ReplayEngine, ReplayOverrides

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def has_db() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


async def test_replay_smoke(has_db):
    if not has_db:
        pytest.skip("no DATABASE_URL")
    end = datetime.now(tz=UTC)
    engine = ReplayEngine()
    result = await engine.run(
        strategy_name="basket_arb",
        config_id="default",
        range_start=end - timedelta(days=14),
        range_end=end,
        starting_capital=Decimal("5000"),
        edge_class="pure_arb",
        overrides=ReplayOverrides(),
    )
    assert result is not None
