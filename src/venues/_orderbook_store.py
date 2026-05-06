"""In-memory store for live orderbooks across all markets.

Keyed by ``(market_id, asset_id)``. Updated by venue adapters as events arrive.
Read by the fill simulator at order-submit time and on every event.

This is process-local. Multiple venues can write to the same store but they
share no logic — each venue's adapter calls ``apply_*`` methods directly.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from src.core.events import OrderBook, PriceLevel, Side


class OrderBookStore:
    def __init__(self) -> None:
        # (market_id, asset_id) -> OrderBook
        self._books: dict[tuple[str, str], OrderBook] = {}
        # Cheap RLock — we expect mostly single-threaded async access but the
        # API service might read from a worker thread for snapshot endpoints.
        self._lock = threading.RLock()

        # Telemetry
        self.snapshots_applied: int = 0
        self.deltas_applied: int = 0

    def get(self, market_id: str, asset_id: str) -> OrderBook | None:
        with self._lock:
            return self._books.get((market_id, asset_id))

    def known_keys(self) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._books.keys())

    def market_count(self) -> int:
        with self._lock:
            return len({m for (m, _) in self._books.keys()})

    def asset_count(self) -> int:
        with self._lock:
            return len(self._books)

    # -----------------------------------------------------------------------
    # Mutations — called by venue adapters
    # -----------------------------------------------------------------------

    def apply_snapshot(
        self,
        market_id: str,
        asset_id: str,
        bids: Iterable[tuple[Decimal, Decimal]],
        asks: Iterable[tuple[Decimal, Decimal]],
        ts: datetime,
    ) -> None:
        with self._lock:
            book = OrderBook(
                market_id=market_id,
                asset_id=asset_id,
                bids=sorted(
                    (PriceLevel(price=p, size=s) for p, s in bids if s > 0),
                    key=lambda lvl: lvl.price,
                    reverse=True,
                ),
                asks=sorted(
                    (PriceLevel(price=p, size=s) for p, s in asks if s > 0),
                    key=lambda lvl: lvl.price,
                ),
                last_update_ts=ts,
            )
            self._books[(market_id, asset_id)] = book
            self.snapshots_applied += 1

    def apply_delta(
        self,
        market_id: str,
        asset_id: str,
        side: Side,
        price: Decimal,
        size: Decimal,
        ts: datetime,
    ) -> None:
        """Set the absolute size at a price level. size=0 removes the level.

        Polymarket's price_change events deliver absolute size at a level, not
        a diff. If your venue emits diffs, convert before calling.
        """
        with self._lock:
            key = (market_id, asset_id)
            book = self._books.get(key)
            if book is None:
                # First sight of this asset — wait for snapshot
                return

            levels = book.bids if side == Side.BUY else book.asks
            for i, lvl in enumerate(levels):
                if lvl.price == price:
                    if size <= 0:
                        levels.pop(i)
                    else:
                        levels[i] = PriceLevel(price=price, size=size)
                    break
            else:
                if size > 0:
                    levels.append(PriceLevel(price=price, size=size))

            # Re-sort — bids desc, asks asc
            if side == Side.BUY:
                book.bids = sorted(levels, key=lambda lvl: lvl.price, reverse=True)
            else:
                book.asks = sorted(levels, key=lambda lvl: lvl.price)

            book.last_update_ts = ts
            self.deltas_applied += 1


# Process-global instance — venues import this directly.
STORE = OrderBookStore()
