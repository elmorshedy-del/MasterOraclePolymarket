"""Central risk-cap enforcement (audit P0-6).

The runner's _signal_within_risk_caps() must reject signals that would
breach a sleeve's max_concurrent_positions or max_exposure_per_market_usd.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from src.core.config import (
    HaircutConfig,
    LoadedSleeveConfig,
    SleeveConfig,
)
from src.core.events import (
    Fill,
    FillType,
    OrderType,
    RealismFlag,
    RuntimeMode,
    Side,
    Signal,
)
from src.execution.position_tracker import PositionTracker
from src.runner.main import Runner
from src.runner.strategy_runner import StrategyRunner


def _sleeve(
    sleeve_id: str = "s1",
    max_concurrent: int = 5,
    max_exposure: str = "500",
    mode: RuntimeMode = RuntimeMode.LIVE_FULL,
) -> LoadedSleeveConfig:
    s = SleeveConfig(
        sleeve_id=sleeve_id,
        strategy="cross_outcome_arb",
        config_id="default",
        edge_class="pure_arb",
        enabled=True,
        mode=mode,
        starting_capital_usd=Decimal("5000"),
        max_concurrent_positions=max_concurrent,
        max_exposure_per_market_usd=Decimal(max_exposure),
    )
    return LoadedSleeveConfig(sleeve=s, config_hash="h", source_path=Path("/tmp"))


def _signal(market: str = "m1", price: str = "0.50",
            size: str = "100", sleeve_id: str = "s1") -> Signal:
    return Signal(
        signal_id=uuid4(),
        sleeve_id=sleeve_id,
        strategy_name="t",
        config_id="default",
        market_id=market,
        asset_id="a",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal(price),
        size=Decimal(size),
        reason="test",
        ts_signal=datetime.now(tz=UTC),
    )


def _fill(market: str = "m1", asset: str = "a", price: str = "0.50",
          size: str = "100", sleeve_id: str = "s1") -> Fill:
    return Fill(
        fill_id=uuid4(),
        order_id=uuid4(),
        sleeve_id=sleeve_id,
        market_id=market,
        asset_id=asset,
        side=Side.BUY,
        price=Decimal(price),
        size=Decimal(size),
        fill_type=FillType.TAKER,
        ts_filled=datetime.now(tz=UTC),
        realism_flag=RealismFlag.CLEAN,
        gas_cost=Decimal("0.10"),
    )


class _StubStrategy:
    name = "t"
    edge_class = "pure_arb"


def _runner_with(sleeve_loaded: LoadedSleeveConfig,
                  n_open: int = 0,
                  market_exposure: dict | None = None) -> tuple[Runner, StrategyRunner]:
    runner = Runner()
    runner.position_tracker = PositionTracker(haircut=HaircutConfig())
    runner.position_tracker.register_sleeve(
        sleeve_loaded.sleeve.sleeve_id,
        sleeve_loaded.sleeve.starting_capital_usd,
        edge_class=sleeve_loaded.sleeve.edge_class,
    )
    for i in range(n_open):
        runner.position_tracker.on_fill(
            _fill(market=f"other_{i}", asset=f"a{i}",
                  sleeve_id=sleeve_loaded.sleeve.sleeve_id),
            "t", "default", "h",
        )
    for market, (price, size) in (market_exposure or {}).items():
        runner.position_tracker.on_fill(
            _fill(market=market, asset="a", price=price, size=size,
                  sleeve_id=sleeve_loaded.sleeve.sleeve_id),
            "t", "default", "h",
        )
    sr = StrategyRunner(sleeve=sleeve_loaded, strategy=_StubStrategy())
    return runner, sr


def test_signal_passes_when_under_caps():
    sleeve = _sleeve(max_concurrent=5, max_exposure="500")
    runner, sr = _runner_with(sleeve, n_open=0)
    assert runner._signal_within_risk_caps(_signal(price="0.50", size="100"), sr) is True


def test_signal_rejected_at_concurrent_cap():
    sleeve = _sleeve(max_concurrent=2, max_exposure="50000")
    runner, sr = _runner_with(sleeve, n_open=2)
    assert runner._signal_within_risk_caps(_signal(market="m_new"), sr) is False


def test_signal_rejected_when_market_exposure_would_exceed_cap():
    sleeve = _sleeve(max_concurrent=10, max_exposure="100")
    runner, sr = _runner_with(sleeve, market_exposure={"market_x": ("0.50", "100")})
    s = _signal(market="market_x", price="0.50", size="200")
    assert runner._signal_within_risk_caps(s, sr) is False


def test_signal_admitted_when_market_exposure_within_cap():
    sleeve = _sleeve(max_concurrent=10, max_exposure="200")
    runner, sr = _runner_with(sleeve, market_exposure={"market_x": ("0.50", "100")})
    s = _signal(market="market_x", price="0.50", size="200")
    assert runner._signal_within_risk_caps(s, sr) is True


def test_no_tracker_admits_signal_conservatively():
    sleeve = _sleeve()
    runner = Runner()
    runner.position_tracker = None
    sr = StrategyRunner(sleeve=sleeve, strategy=_StubStrategy())
    assert runner._signal_within_risk_caps(_signal(), sr) is True


def test_market_order_skips_exposure_calc():
    sleeve = _sleeve(max_concurrent=10, max_exposure="50")
    runner, sr = _runner_with(sleeve)
    s = Signal(
        signal_id=uuid4(),
        sleeve_id=sleeve.sleeve.sleeve_id,
        strategy_name="t", config_id="default",
        market_id="m1", asset_id="a",
        side=Side.BUY, order_type=OrderType.MARKET,
        price=None, size=Decimal("1000"),
        reason="big market order", ts_signal=datetime.now(tz=UTC),
    )
    assert runner._signal_within_risk_caps(s, sr) is True
