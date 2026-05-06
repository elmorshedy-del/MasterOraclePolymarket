"""Phase 1 smoke tests — verify venue plugins discover and normalize correctly."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal


def test_orderbook_store_snapshot_and_delta():
    from src.core.events import Side
    from src.venues._orderbook_store import OrderBookStore

    store = OrderBookStore()
    ts = datetime.now(tz=UTC)

    store.apply_snapshot(
        market_id="m1",
        asset_id="a1",
        bids=[(Decimal("0.50"), Decimal("100")), (Decimal("0.49"), Decimal("200"))],
        asks=[(Decimal("0.52"), Decimal("150"))],
        ts=ts,
    )

    book = store.get("m1", "a1")
    assert book is not None
    assert book.best_bid().price == Decimal("0.50")
    assert book.best_ask().price == Decimal("0.52")
    assert store.market_count() == 1
    assert store.asset_count() == 1

    # Apply a delta — increase the best bid size
    store.apply_delta("m1", "a1", Side.BUY, Decimal("0.50"), Decimal("250"), ts)
    book2 = store.get("m1", "a1")
    assert book2.best_bid().size == Decimal("250")

    # Remove a level
    store.apply_delta("m1", "a1", Side.SELL, Decimal("0.52"), Decimal("0"), ts)
    book3 = store.get("m1", "a1")
    assert book3.best_ask() is None


def test_polymarket_clob_normalize_book_event():
    from src.venues.polymarket_clob import _normalize

    msg = {
        "event_type": "book",
        "asset_id": "asset-1",
        "market": "market-1",
        "timestamp": "1700000000000",
        "hash": "abc123",
        "bids": [{"price": "0.50", "size": "100"}],
        "asks": [{"price": "0.52", "size": "150"}],
    }
    event = _normalize(msg)
    assert event is not None
    assert event.event_type.value == "book_snapshot"
    assert event.market_id == "market-1"
    assert event.asset_id == "asset-1"
    assert event.payload["hash"] == "abc123"


def test_polymarket_clob_normalize_trade_event():
    from src.venues.polymarket_clob import _normalize

    msg = {
        "event_type": "last_trade_price",
        "asset_id": "asset-1",
        "market": "market-1",
        "timestamp": "1700000000000",
        "price": "0.51",
        "size": "10",
        "side": "BUY",
    }
    event = _normalize(msg)
    assert event is not None
    assert event.event_type.value == "trade_print"
    assert event.payload["price"] == "0.51"
    assert event.payload["side"] == "buy"


def test_polymarket_clob_normalize_unknown_event_returns_none():
    from src.venues.polymarket_clob import _normalize

    assert _normalize({"event_type": "something_new"}) is None
    assert _normalize({}) is None


def test_polymarket_markets_parses_gamma_clob_token_ids():
    from src.venues.polymarket_markets import _parse_market

    meta = _parse_market({
        "id": "540816",
        "conditionId": "0xabc",
        "slug": "sample-market",
        "question": "Sample market?",
        "clobTokenIds": '["yes-token", "no-token"]',
        "endDate": "2026-07-31T12:00:00Z",
        "orderPriceMinTickSize": "0.01",
        "volume24hr": 123.45,
        "liquidity": "1000",
        "active": True,
        "closed": False,
    })

    assert meta is not None
    assert meta.market_id == "0xabc"
    assert meta.asset_ids == ("yes-token", "no-token")


def test_news_rss_canonical_url_dedupe_setup():
    """News adapter should construct without errors and have empty seen-set initially."""
    from src.venues.news_rss import NewsRSS

    n = NewsRSS()
    assert n.name == "news_rss"
    assert n.events_emitted == 0
    assert len(n._seen_urls) == 0
    assert len(n.feeds) >= 1


def test_kalshi_disabled_by_default():
    from src.venues.kalshi import Kalshi

    k = Kalshi()
    assert k.enabled is False


def test_deribit_disabled_by_default():
    from src.venues.deribit import Deribit

    d = Deribit()
    assert d.enabled is False


def test_binance_perp_disabled_by_default():
    from src.venues.binance_perp import BinancePerp

    b = BinancePerp()
    assert b.enabled is False


def test_reddit_disabled_by_default():
    from src.venues.reddit import Reddit

    r = Reddit()
    assert r.enabled is False


def test_event_writer_buffer_and_dedupe():
    from src.core.events import EventType, MarketEvent
    from src.db.event_writer import EventWriter

    w = EventWriter(max_buffer=5)
    for i in range(7):
        ev = MarketEvent.make(
            event_type=EventType.BOOK_DELTA,
            venue="polymarket",
            payload={"i": i},
            market_id="m",
        )
        w.submit(ev)
    # 7 submitted, max_buffer 5 → 2 dropped
    assert w.events_dropped == 2
    assert len(w._buffer) == 5
