"""Reddit firehose adapter.

Streams new posts from a configured set of subreddits (default: politics,
cryptocurrency, sportsbook). Emits NEWS_ITEM events tagged with subreddit.

Disabled by default — requires Reddit API credentials in env:
  - REDDIT_CLIENT_ID
  - REDDIT_CLIENT_SECRET
  - REDDIT_USER_AGENT

If credentials are missing the adapter logs a warning and idles — it does
not crash the runner.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timezone

from src.core.events import EventType, MarketEvent, MarketMeta
from src.core.interfaces import MarketDataSource

logger = logging.getLogger(__name__)


VENUE = "reddit"
DEFAULT_SUBREDDITS = ("politics", "cryptocurrency", "sportsbook")


class Reddit:
    name: str = "reddit"

    def __init__(
        self,
        subreddits: Iterable[str] = DEFAULT_SUBREDDITS,
        enabled: bool = False,
    ) -> None:
        self.subreddits = list(subreddits)
        self.enabled = enabled

        self._stop = asyncio.Event()
        self._reddit = None  # praw.Reddit instance, lazy-loaded

        self.events_emitted: int = 0
        self.last_event_at: datetime | None = None

    async def start(self) -> None:
        client_id = os.environ.get("REDDIT_CLIENT_ID")
        client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
        user_agent = os.environ.get("REDDIT_USER_AGENT")

        if not (client_id and client_secret and user_agent):
            logger.warning(
                "[reddit] credentials missing; adapter will idle. "
                "Set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT to enable."
            )
            return

        # Lazy import — praw may not be installed in lean deploys
        try:
            import praw
        except ImportError:
            logger.warning("[reddit] praw not installed — adapter idle")
            return

        self._reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
            check_for_async=False,
        )

    async def stop(self) -> None:
        self._stop.set()

    async def stream_events(self) -> AsyncIterator[MarketEvent]:
        if self._reddit is None:
            # Idle without credentials — just sleep until stop.
            await self._stop.wait()
            return

        # praw is sync; use thread-pumped streams.
        from itertools import cycle

        sub_str = "+".join(self.subreddits)

        def _fetch_new(limit: int = 25):
            return list(self._reddit.subreddit(sub_str).new(limit=limit))

        seen: set[str] = set()
        seen_max = 5_000

        # Seed: skip backlog
        try:
            for post in await asyncio.to_thread(_fetch_new, 100):
                seen.add(post.id)
        except Exception:  # noqa: BLE001
            logger.exception("[reddit] seed failed")

        for _ in cycle([0]):
            if self._stop.is_set():
                break
            try:
                posts = await asyncio.to_thread(_fetch_new, 25)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[reddit] fetch failed: %s", exc)
                posts = []

            for post in posts:
                if post.id in seen:
                    continue
                seen.add(post.id)
                if len(seen) > seen_max:
                    seen = set(list(seen)[seen_max // 2 :])

                ts = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
                self.events_emitted += 1
                self.last_event_at = ts
                yield MarketEvent.make(
                    event_type=EventType.NEWS_ITEM,
                    venue=VENUE,
                    payload={
                        "source": f"reddit/{post.subreddit.display_name}",
                        "url": f"https://reddit.com{post.permalink}",
                        "title": post.title,
                        "summary": post.selftext[:500] if post.selftext else None,
                        "score": post.score,
                        "author": str(post.author) if post.author else None,
                    },
                    ts=ts,
                )

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                continue

    async def list_markets(self) -> Iterable[MarketMeta]:
        return []


def plugin() -> Reddit:
    return Reddit()
