"""Latency injection helper.

The system targets a fixed end-to-end latency (default 1500ms — see
DESIGN.md §5). This helper sleeps the appropriate amount before an order
is considered to have arrived at the venue, then re-snapshots the book.

Latency is a SYSTEM constant, not a strategy config. Replay variants can
override it for "what-if" analysis (one-button preset on the dashboard).
"""

from __future__ import annotations

import asyncio

from src.core.config import LatencyModel


async def apply_latency(latency: LatencyModel) -> None:
    """Sleep for the configured total latency budget."""
    total_secs = latency.total_ms() / 1000.0
    if total_secs > 0:
        await asyncio.sleep(total_secs)
