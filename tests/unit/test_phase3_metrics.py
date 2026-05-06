"""Unit tests for metric plugins (matched to actual classes in src/analytics/metrics/)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from src.analytics.metric_service import MetricService
from src.analytics.metrics.avg_trade import AvgTradeMetric
from src.analytics.metrics.capacity_estimate import CapacityEstimateMetric
from src.analytics.metrics.max_drawdown import MaxDrawdownMetric
from src.analytics.metrics.profit_factor import ProfitFactorMetric
from src.analytics.metrics.sharpe import SharpeMetric
from src.analytics.metrics.sortino import SortinoMetric
from src.analytics.metrics.total_pnl import TotalPnLMetric
from src.analytics.metrics.trade_count import TradeCountMetric
from src.analytics.metrics.win_rate import WinRateMetric
from src.core.events import FillType, RealismFlag, Side, Trade


def _trade(pnl_after: float, pnl_raw: float | None = None, days_offset: float = 0.0) -> Trade:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return Trade(
        trade_id=uuid4(),
        sleeve_id="s",
        strategy_name="t",
        config_id="default",
        market_id="m",
        asset_id="a",
        side=Side.BUY,
        entry_price=Decimal("0.50"),
        entry_size=Decimal("100"),
        entry_ts=base + timedelta(days=days_offset),
        exit_price=Decimal("0.51"),
        exit_size=Decimal("100"),
        exit_ts=base + timedelta(days=days_offset, hours=1),
        pnl=Decimal(str(pnl_raw if pnl_raw is not None else pnl_after)),
        pnl_after_haircut=Decimal(str(pnl_after)),
        realism_flag=RealismFlag.CLEAN,
        fill_type=FillType.TAKER,
    )


def test_total_pnl_sums_after_haircut():
    trades = [_trade(10), _trade(-5), _trade(3)]
    assert TotalPnLMetric().compute(trades) == 8.0


def test_win_rate():
    trades = [_trade(10), _trade(-5), _trade(3), _trade(-1)]
    assert WinRateMetric().compute(trades) == 0.5


def test_profit_factor():
    trades = [_trade(10), _trade(-5), _trade(5)]
    pf = ProfitFactorMetric().compute(trades)
    assert abs(pf - 3.0) < 1e-6


def test_max_drawdown_returns_positive_dollars():
    """MaxDrawdownMetric returns the worst drawdown as a POSITIVE number."""
    trades = [_trade(10, days_offset=0), _trade(-5, days_offset=1),
              _trade(-10, days_offset=2), _trade(20, days_offset=3)]
    # equity curve: 10, 5, -5, 15. Peak=10, then -5 → DD = 15
    dd = MaxDrawdownMetric().compute(trades)
    assert dd == 15.0


def test_sharpe_with_few_trades_returns_zero():
    assert SharpeMetric().compute([]) == 0.0
    assert SharpeMetric().compute([_trade(10)]) == 0.0


def test_sortino_no_downside_returns_inf_or_zero():
    assert SortinoMetric().compute([]) == 0.0
    # All wins, mean > 0 → Sortino = +inf
    res = SortinoMetric().compute([_trade(10), _trade(5), _trade(3)])
    assert res == float("inf")


def test_avg_trade_uses_pnl_after_haircut():
    trades = [_trade(10), _trade(-5), _trade(3)]
    assert abs(AvgTradeMetric().compute(trades) - (10 + -5 + 3) / 3) < 1e-6


def test_trade_count():
    assert TradeCountMetric().compute([]) == 0.0
    assert TradeCountMetric().compute([_trade(1), _trade(2), _trade(3)]) == 3.0


def test_capacity_estimate_pnl_per_notional_dollar():
    trades = [_trade(10), _trade(-5)]
    # notional per trade = 0.50 * 100 = 50; total notional = 100; total pnl = 5
    assert abs(CapacityEstimateMetric().compute(trades) - 0.05) < 1e-6


def test_metric_service_compute_all_returns_all_loaded_metrics():
    svc = MetricService()
    out = svc.compute_all([_trade(10), _trade(-5)])
    # At minimum these should be present
    expected = {"sharpe", "sortino", "total_pnl", "max_drawdown", "win_rate",
                "profit_factor", "trade_count", "avg_trade", "capacity_estimate"}
    assert expected.issubset(out.keys())
    assert out["total_pnl"] == 5.0
    assert out["trade_count"] == 2.0
    assert out["win_rate"] == 0.5
