"""Kalshi public API adapter (read-only).

Polls Kalshi's public market endpoints for prices and trades on the small
manually-mapped set of markets that overlap with Polymarket events
(elections, FOMC dates, CPI prints, championship games, etc.).

Kalshi has both REST and WS APIs. The WS requires authenticated session
cookies even for public data; the REST endpoints work unauthenticated and
suffice for our paper/research use case (we're not trading on Kalshi yet).

Disabled by default in pipes.yaml — enable once a market mapping table is
populated.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from src.core.events import EventType, MarketEvent, MarketMeta

logger = logging.getLogger(__name__)


VENUE = "kalshi"
DEFAULT_API_BASE = "https://trading-api.kalshi.com/trade-api/v2"


class Kalshi:
    name: str = "kalshi"

    def __init__(
        self,
        api_base: str | None = None,
        poll_interval_secs: float = 10.0,
        market_tickers: Iterable[str] = (),
        enabled: bool = False,
    ) -> None:
        self.api_base = api_base or os.environ.get("KALSHI_API_BASE", DEFAULT_API_BASE)
        self.poll_interval_secs = poll_interval_secs
        self.market_tickers = list(market_tickers)
        self.enabled = enabled

        self._stop = asyncio.Event()
        self._client: httpx.AsyncClient | None = None
        self._last_prices: dict[str, Decimal] = {}

        self.events_emitted: int = 0
        self.requests_made: int = 0
        self.last_poll_at: datetime | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.api_base,
            headers={"Accept": "application/json"},
            timeout=20.0,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def stream_events(self) -> AsyncIterator[MarketEvent]:
        if self._client is None:
            raise RuntimeError("call start() before stream_events()")

        if not self.market_tickers:
            logger.info("[kalshi] no tickers configured — adapter idle")

        while not self._stop.is_set():
            for ticker in self.market_tickers:
                if self._stop.is_set():
                    break
                try:
                    event = await self._fetch_ticker(ticker)
                    if event is not None:
                        yield event
                        self.events_emitted += 1
                except Exception as exc:
                    logger.warning("[kalshi] %s fetch failed: %s", ticker, exc)
            self.last_poll_at = datetime.now(tz=UTC)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval_secs)
            except TimeoutError:
                continue

    async def list_markets(self) -> Iterable[MarketMeta]:
        return []

    # --------------------------------------------------------------------------

    async def _fetch_ticker(self, ticker: str) -> MarketEvent | None:
        assert self._client is not None
        self.requests_made += 1
        try:
            resp = await self._client.get(f"/markets/{ticker}")
            resp.raise_for_status()
        except httpx.HTTPError:
            return None

        data = resp.json()
        market = data.get("market", data)

        bid_raw = market.get("yes_bid")
        ask_raw = market.get("yes_ask")
        last = market.get("last_price")
        if bid_raw is None and ask_raw is None and last is None:
            return None

        # Kalshi prices are 1–99 (cents). Convert to 0.01–0.99 to match Polymarket.
        def _cents_to_prob(v) -> Decimal | None:
            if v is None:
                return None
            try:
                return (Decimal(str(v)) / Decimal(100)).quantize(Decimal("0.0001"))
            except Exception:
                return None

        bid = _cents_to_prob(bid_raw)
        ask = _cents_to_prob(ask_raw)
        last_price = _cents_to_prob(last)

        # Use ticker as both market_id and asset_id for now; in §1 mapping
        # work, we'll join Kalshi tickers to Polymarket conditionIds.
        ts = datetime.now(tz=UTC)
        return MarketEvent.make(
            event_type=EventType.BOOK_SNAPSHOT,
            venue=VENUE,
            payload={
                "ticker": ticker,
                "bid": str(bid) if bid is not None else None,
                "ask": str(ask) if ask is not None else None,
                "last": str(last_price) if last_price is not None else None,
                "volume_24h": market.get("volume_24h"),
            },
            market_id=ticker,
            asset_id=ticker,
            ts=ts,
        )


def plugin() -> Kalshi:
    return Kalshi()
