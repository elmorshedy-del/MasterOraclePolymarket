"""RSS news firehose.

Polls a configured set of free RSS feeds and emits NEWS_ITEM events as new
items appear. Dedupe is by canonical URL.

Default feeds: Reuters, AP, BBC, CNN, Bloomberg headlines, ESPN. Replace the
list via env var ``NEWS_RSS_FEEDS`` (comma-separated URLs) without code change.

This adapter is intentionally simple — news strategies depend on having
*some* timestamped news stream. Phase 5+ may add structured providers
(Polygon News, Benzinga, etc.) but that's a separate venue.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timezone
from typing import Any

import feedparser

from src.core.events import EventType, MarketEvent, MarketMeta
from src.core.interfaces import MarketDataSource

logger = logging.getLogger(__name__)


VENUE = "news"

DEFAULT_FEEDS: tuple[tuple[str, str], ...] = (
    # (source_name, feed_url)
    ("reuters",   "https://feeds.reuters.com/reuters/topNews"),
    ("ap",        "https://feeds.apnews.com/rss/apf-topnews"),
    ("bbc",       "http://feeds.bbci.co.uk/news/rss.xml"),
    ("cnn",       "http://rss.cnn.com/rss/cnn_topstories.rss"),
    ("bloomberg", "https://feeds.bloomberg.com/markets/news.rss"),
    ("espn",      "https://www.espn.com/espn/rss/news"),
    # Crypto-specific
    ("coindesk",  "https://www.coindesk.com/arc/outboundfeeds/rss/"),
)


class NewsRSS:
    name: str = "news_rss"

    def __init__(
        self,
        feeds: Iterable[tuple[str, str]] | None = None,
        poll_interval_secs: float = 60.0,
        enabled: bool = True,
    ) -> None:
        feeds_env = os.environ.get("NEWS_RSS_FEEDS")
        if feeds_env:
            self.feeds = tuple(
                (url.split("//")[-1].split("/")[0], url.strip())
                for url in feeds_env.split(",")
                if url.strip()
            )
        else:
            self.feeds = tuple(feeds) if feeds is not None else DEFAULT_FEEDS

        self.poll_interval_secs = poll_interval_secs
        self.enabled = enabled

        self._stop = asyncio.Event()
        self._seen_urls: set[str] = set()
        self._seen_max: int = 20_000

        self.events_emitted: int = 0
        self.fetch_failures: int = 0
        self.last_poll_at: datetime | None = None

    async def start(self) -> None:
        # feedparser is sync; we offload to thread when fetching.
        return None

    async def stop(self) -> None:
        self._stop.set()

    async def stream_events(self) -> AsyncIterator[MarketEvent]:
        # Seed: skip the initial backlog by recording all current URLs without
        # emitting. We only want NEW items to fire signals.
        await self._seed_initial()

        while not self._stop.is_set():
            for source, url in self.feeds:
                if self._stop.is_set():
                    break
                items = await self._fetch_feed(source, url)
                for ev in items:
                    yield ev
                    self.events_emitted += 1
            self.last_poll_at = datetime.now(tz=timezone.utc)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval_secs)
            except asyncio.TimeoutError:
                continue

    async def list_markets(self) -> Iterable[MarketMeta]:
        return []

    # --------------------------------------------------------------------------

    async def _seed_initial(self) -> None:
        for source, url in self.feeds:
            try:
                parsed = await asyncio.to_thread(feedparser.parse, url)
                for entry in parsed.entries:
                    self._seen_urls.add(_canonical_url(entry))
            except Exception:  # noqa: BLE001
                logger.warning("[news_rss] seed failed for %s", source)

    async def _fetch_feed(self, source: str, url: str) -> list[MarketEvent]:
        try:
            parsed = await asyncio.to_thread(feedparser.parse, url)
        except Exception:  # noqa: BLE001
            self.fetch_failures += 1
            return []

        out: list[MarketEvent] = []
        for entry in parsed.entries:
            canon = _canonical_url(entry)
            if not canon or canon in self._seen_urls:
                continue
            self._seen_urls.add(canon)
            if len(self._seen_urls) > self._seen_max:
                self._seen_urls = set(list(self._seen_urls)[self._seen_max // 2 :])

            ts = _entry_ts(entry)
            payload: dict[str, Any] = {
                "source": source,
                "url": canon,
                "title": getattr(entry, "title", None),
                "summary": getattr(entry, "summary", None),
                "tags": [t.term for t in getattr(entry, "tags", []) if hasattr(t, "term")],
            }
            out.append(
                MarketEvent.make(
                    event_type=EventType.NEWS_ITEM,
                    venue=VENUE,
                    payload=payload,
                    ts=ts,
                )
            )
        return out


def _canonical_url(entry) -> str:
    return (
        getattr(entry, "link", "")
        or getattr(entry, "id", "")
        or getattr(entry, "guid", "")
    )


def _entry_ts(entry) -> datetime:
    parsed = (
        getattr(entry, "published_parsed", None)
        or getattr(entry, "updated_parsed", None)
    )
    if parsed is None:
        return datetime.now(tz=timezone.utc)
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def plugin() -> NewsRSS:
    return NewsRSS()
