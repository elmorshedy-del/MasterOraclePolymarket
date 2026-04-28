"""Phase 0 smoke tests — verify imports and basic structure."""

from __future__ import annotations

from decimal import Decimal


def test_event_types_import():
    from src.core.events import (
        EventType,
        FillType,
        OrderType,
        RealismFlag,
        RuntimeMode,
        Side,
    )

    assert Side.BUY != Side.SELL
    assert OrderType.MARKET != OrderType.LIMIT
    assert FillType.TAKER != FillType.MAKER_FAST
    assert RealismFlag.CLEAN.value == "clean"
    assert RuntimeMode.LIVE_FULL.value == "live_full"
    assert EventType.BOOK_DELTA.value == "book_delta"


def test_orderbook_basics():
    from src.core.events import OrderBook, PriceLevel, Side

    book = OrderBook(
        market_id="m1",
        asset_id="a1",
        bids=[PriceLevel(price=Decimal("0.50"), size=Decimal("100")),
              PriceLevel(price=Decimal("0.49"), size=Decimal("200"))],
        asks=[PriceLevel(price=Decimal("0.52"), size=Decimal("150")),
              PriceLevel(price=Decimal("0.53"), size=Decimal("300"))],
    )

    assert book.best_bid().price == Decimal("0.50")
    assert book.best_ask().price == Decimal("0.52")
    assert book.mid() == Decimal("0.51")
    assert book.spread() == Decimal("0.02")
    assert book.depth_at_or_better(Side.BUY, Decimal("0.50")) == Decimal("100")
    assert book.depth_at_or_better(Side.SELL, Decimal("0.52")) == Decimal("150")


def test_interfaces_import():
    from src.core.interfaces import (
        Allocator,
        FillSimulator,
        MarketDataSource,
        Metric,
        Strategy,
        Tag,
    )

    assert MarketDataSource is not None
    assert Strategy is not None
    assert FillSimulator is not None
    assert Tag is not None
    assert Metric is not None
    assert Allocator is not None


def test_system_config_defaults():
    from src.core.config import RuntimeConfig

    rt = RuntimeConfig()
    assert rt.latency.total_ms() == 1500
    assert rt.haircut.default == Decimal("0.22")
    assert rt.calibration.enabled is False
    assert rt.fill_simulator == "event_replay"
