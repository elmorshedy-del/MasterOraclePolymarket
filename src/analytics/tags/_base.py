"""Shared helpers for tag plugins.

A TagContext gathers everything a tag plugin might need to compute its
value: the Trade, the MarketMeta, the order book at entry/exit, recent
events near the trade, recent news headlines, etc.

Tag plugins MUST be deterministic given the context — no clock reads, no
network calls, no randomness — so retroactive tagging produces identical
results to live tagging.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.core.events import OrderBook, Trade


@dataclass
class TagContext:
    trade: Trade

    # Market metadata (resolved by the tag service before invoking plugins)
    market_category: str | None = None
    market_subcategory: str | None = None
    end_time: datetime | None = None
    volume_24h_usd: Decimal | None = None

    # Snapshot of order book at entry, if available
    book_at_entry: OrderBook | None = None

    # Trades observed in the 30 seconds before this trade's entry
    pre_entry_trade_prints: list[dict[str, Any]] = field(default_factory=list)

    # News headlines in the 5 minutes before entry (urls only — full payload kept off context)
    pre_entry_news_count: int = 0

    # Wallet seen on the opposite side near entry, if any (counterparty heuristic)
    counterparty_wallet: str | None = None

    # Free-form extras for future plugins
    extras: dict[str, Any] = field(default_factory=dict)
