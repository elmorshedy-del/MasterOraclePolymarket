"""Unit tests for tag plugins (matched to actual classes in src/analytics/tags/)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from src.analytics.tags.counterparty_estimate import SHARP_WALLETS, CounterpartyEstimateTag
from src.analytics.tags.day_of_week import DayOfWeekTag
from src.analytics.tags.entry_price_bucket import EntryPriceBucketTag
from src.analytics.tags.liquidity_bucket import LiquidityBucketTag
from src.analytics.tags.market_category import MarketCategoryTag
from src.analytics.tags.market_subcategory import MarketSubcategoryTag
from src.analytics.tags.news_regime import NewsRegimeTag
from src.analytics.tags.orderbook_state_bucket import OrderbookStateBucketTag
from src.analytics.tags.time_of_day import TimeOfDayBucketTag
from src.analytics.tags.time_to_resolution_bucket import TimeToResolutionBucketTag
from src.core.events import FillType, OrderBook, PriceLevel, RealismFlag, Side, Trade


def _trade(price: float = 0.50, ts: datetime | None = None) -> Trade:
    return Trade(
        trade_id=uuid4(),
        sleeve_id="s", strategy_name="t", config_id="default",
        market_id="m", asset_id="a",
        side=Side.BUY,
        entry_price=Decimal(str(price)),
        entry_size=Decimal("100"),
        entry_ts=ts or datetime(2026, 4, 27, 10, 30, tzinfo=UTC),
        exit_price=None, exit_size=None, exit_ts=None,
        pnl=None, pnl_after_haircut=None,
        realism_flag=RealismFlag.CLEAN, fill_type=FillType.TAKER,
    )


def test_entry_price_bucket():
    p = EntryPriceBucketTag()
    assert p.tag_trade(_trade(0.02), {}) == "<$0.05"
    assert p.tag_trade(_trade(0.10), {}) == "$0.05-0.25"
    assert p.tag_trade(_trade(0.50), {}) == "$0.25-0.75"
    assert p.tag_trade(_trade(0.85), {}) == "$0.75-0.95"
    assert p.tag_trade(_trade(0.97), {}) == ">$0.95"


def test_time_of_day_bucket_uses_utc_hour():
    p = TimeOfDayBucketTag()
    base = datetime(2026, 4, 27, tzinfo=UTC)
    assert p.tag_trade(_trade(ts=base.replace(hour=2)),  {}) == "0-6"
    assert p.tag_trade(_trade(ts=base.replace(hour=8)),  {}) == "6-12"
    assert p.tag_trade(_trade(ts=base.replace(hour=14)), {}) == "12-18"
    assert p.tag_trade(_trade(ts=base.replace(hour=22)), {}) == "18-24"


def test_day_of_week_monday_is_zero():
    # 2026-04-27 is a Monday
    assert DayOfWeekTag().tag_trade(_trade(ts=datetime(2026, 4, 27, tzinfo=UTC)), {}) == 0
    # Sunday → 6
    assert DayOfWeekTag().tag_trade(_trade(ts=datetime(2026, 5, 3, tzinfo=UTC)), {}) == 6


def test_liquidity_bucket_thresholds():
    p = LiquidityBucketTag()
    assert p.tag_trade(_trade(), {})  == "unknown"
    assert p.tag_trade(_trade(), {"volume_24h_usd": Decimal("500")})  == "thin"
    assert p.tag_trade(_trade(), {"volume_24h_usd": Decimal("5000")}) == "medium"
    assert p.tag_trade(_trade(), {"volume_24h_usd": Decimal("50000")}) == "thick"


def test_market_category_lowercases():
    p = MarketCategoryTag()
    assert p.tag_trade(_trade(), {"market_category": "Politics"}) == "politics"
    assert p.tag_trade(_trade(), {}) == "uncategorized"


def test_market_subcategory_lowercases_or_none():
    p = MarketSubcategoryTag()
    assert p.tag_trade(_trade(), {"market_subcategory": "WEATHER/NYC/Temp"}) == "weather/nyc/temp"
    assert p.tag_trade(_trade(), {}) is None


def test_orderbook_state_bucket():
    p = OrderbookStateBucketTag()
    assert p.tag_trade(_trade(), {}) == "unknown"

    book = OrderBook(
        market_id="m", asset_id="a",
        bids=[PriceLevel(price=Decimal("0.49"), size=Decimal("100"))],
        asks=[PriceLevel(price=Decimal("0.51"), size=Decimal("100"))],
    )
    # mid 0.50 * (100+100) = 100 → thin
    assert p.tag_trade(_trade(), {"book_at_entry": book}) == "thin"

    thick_book = OrderBook(
        market_id="m", asset_id="a",
        bids=[PriceLevel(price=Decimal("0.49"), size=Decimal("3000"))],
        asks=[PriceLevel(price=Decimal("0.51"), size=Decimal("3000"))],
    )
    # mid 0.50 * 6000 = 3000 → thick
    assert p.tag_trade(_trade(), {"book_at_entry": thick_book}) == "thick"


def test_news_regime_thresholds():
    p = NewsRegimeTag()
    assert p.tag_trade(_trade(), {"pre_entry_news_count": 0}) == "calm"
    assert p.tag_trade(_trade(), {"pre_entry_news_count": 2}) == "news_event"
    assert p.tag_trade(_trade(), {"pre_entry_news_count": 10}) == "post_event"
    assert p.tag_trade(_trade(), {}) == "calm"  # default count is 0


def test_counterparty_estimate_buckets():
    p = CounterpartyEstimateTag()
    assert p.tag_trade(_trade(), {}) == "unknown"
    assert p.tag_trade(_trade(), {"counterparty_wallet": "0xrandom"}) == "retail"
    # Seeded via constants
    sample = next(iter(SHARP_WALLETS))
    assert p.tag_trade(_trade(), {"counterparty_wallet": sample}) == "sharp"


def test_time_to_resolution_bucket():
    p = TimeToResolutionBucketTag()
    entry = datetime(2026, 4, 27, 10, 0, tzinfo=UTC)
    assert p.tag_trade(_trade(ts=entry), {"end_time": entry + timedelta(minutes=30)}) == "<1h"
    assert p.tag_trade(_trade(ts=entry), {"end_time": entry + timedelta(hours=10)}) == "1-24h"
    assert p.tag_trade(_trade(ts=entry), {"end_time": entry + timedelta(days=3)}) == "1-7d"
    assert p.tag_trade(_trade(ts=entry), {"end_time": entry + timedelta(days=30)}) == ">7d"
    assert p.tag_trade(_trade(), {}) == "unknown"
