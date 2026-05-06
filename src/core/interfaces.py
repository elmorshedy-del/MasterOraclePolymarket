"""Plugin contracts.

Anything in ``src/venues/``, ``src/execution/``, ``src/strategies/<name>/``,
``src/analytics/tags/``, and ``src/analytics/metrics/`` must implement one of
these protocols. The plugin loader auto-discovers them at startup.

Protocols are runtime-checkable so the loader can verify implementations
before activating them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import Any, Protocol, runtime_checkable

from src.core.events import (
    Fill,
    MarketEvent,
    MarketMeta,
    Order,
    OrderBook,
    Signal,
    Trade,
)

# ---------------------------------------------------------------------------
# Market data sources (venues)
# ---------------------------------------------------------------------------


@runtime_checkable
class MarketDataSource(Protocol):
    """A venue or external data feed.

    Implementations: PolymarketCLOB, PolymarketActivity, KalshiAPI, DeribitWS,
    BinancePerp, NewsRSS, RedditFirehose, etc.

    All sources normalize their native events into ``MarketEvent`` and stream
    them through ``stream_events``. Long-lived sources (websockets) yield
    forever; one-shot sources may complete.
    """

    name: str
    enabled: bool

    async def start(self) -> None:
        """Open connections, authenticate, etc. Called once on platform boot."""
        ...

    async def stop(self) -> None:
        """Graceful shutdown. Idempotent."""
        ...

    async def stream_events(self) -> AsyncIterator[MarketEvent]:
        """Async iterator of normalized events.

        Implementations are responsible for reconnect/backoff. The runner
        treats this iterator as infinite for live sources.
        """
        ...

    async def list_markets(self) -> Iterable[MarketMeta]:
        """Snapshot of currently-known markets on this venue."""
        ...


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@runtime_checkable
class Strategy(Protocol):
    """A single strategy plugin.

    A strategy is **stateless** at the architectural level — its state is
    derived from market state passed in. State that crosses events
    (e.g., recently-opened positions) is kept on the runner side and provided
    via the ``state`` param. This makes replay deterministic.
    """

    name: str
    edge_class: str           # "pure_arb" | "maker" | "directional" | "copy" | "tail" | ...

    async def on_event(
        self,
        event: MarketEvent,
        state: dict[str, Any],
    ) -> list[Signal]:
        """Called for every event the strategy is subscribed to.

        Returns a (possibly empty) list of new signals. The runner is
        responsible for forwarding signals to the fill simulator under the
        right runtime mode.
        """
        ...

    def required_event_types(self) -> set[str]:
        """Optional optimization: tell the runner which event types to forward.

        The default plugin loader treats this as advisory; runners may use
        it to skip uninterested strategies on hot paths.
        """
        ...

    def required_data_sources(self) -> set[str]:
        """Names of MarketDataSources this strategy needs to function.

        If any required source is disabled, the strategy is auto-paused.
        """
        ...


# ---------------------------------------------------------------------------
# Fill simulators
# ---------------------------------------------------------------------------


@runtime_checkable
class FillSimulator(Protocol):
    """Translates Orders into Fills.

    Implementations:
      - ``EventReplayFillSimulator`` (Tier 2, default): event-tape replay
      - ``CalibratedFillSimulator`` (Tier 3, opt-in): event replay + real
        shadow-order calibration constants
      - ``SnapshotFillSimulator`` (Tier 1, deprecated, kept for comparison)
    """

    name: str

    async def submit(
        self,
        order: Order,
        book: OrderBook,
    ) -> list[Fill]:
        """Submit an order, return any immediate fills.

        For taker orders: fills emitted synchronously from current book.
        For maker orders: 0 fills returned synchronously; further fills
        arrive via ``on_event``.
        """
        ...

    async def on_event(
        self,
        event: MarketEvent,
        book: OrderBook,
    ) -> list[Fill]:
        """Process an event for any open resting maker orders.

        Returns any fills that occur as a consequence of this event.
        """
        ...

    async def cancel(self, order_id: Any) -> None:
        """Cancel a resting order. No-op for already-filled orders."""
        ...


# ---------------------------------------------------------------------------
# Analytics: trade tags
# ---------------------------------------------------------------------------


@runtime_checkable
class Tag(Protocol):
    """A trade-tagging plugin.

    Each Tag plugin contributes one column to the analytics matrix. The
    plugin loader auto-applies all enabled tags to every Trade on close.

    Examples: market_category, liquidity_bucket, entry_price_bucket,
    counterparty_estimate, time_of_day, news_regime, etc.
    """

    name: str            # used as the column key in dashboards
    description: str

    def tag_trade(
        self,
        trade: Trade,
        context: dict[str, Any],
    ) -> Any:
        """Compute the tag value for a trade.

        ``context`` includes book state at entry/exit, market meta, recent
        events near the trade, etc. Tags MUST be deterministic given the
        context — no clock reads, no network calls.
        """
        ...


# ---------------------------------------------------------------------------
# Analytics: metrics
# ---------------------------------------------------------------------------


@runtime_checkable
class Metric(Protocol):
    """A scalar performance metric over a set of trades.

    Examples: Sharpe, Sortino, max_drawdown, win_rate, profit_factor,
    avg_winner, capacity_estimate.

    The dashboard's per-sleeve scorecard auto-includes every Metric plugin.
    """

    name: str
    higher_is_better: bool

    def compute(self, trades: list[Trade]) -> float:
        ...


# ---------------------------------------------------------------------------
# Allocators (deferred — for use after V1)
# ---------------------------------------------------------------------------


@runtime_checkable
class Allocator(Protocol):
    """Computes capital weights across sleeves.

    Not used in V1 (equal-weight $5k per sleeve). Will be populated in
    month 3+ to backtest allocation policies on top of the live trade log.
    """

    name: str

    def weights(
        self,
        sleeves: list[str],
        history: dict[str, list[Trade]],
    ) -> dict[str, float]:
        """Return weight per sleeve, summing to 1.0."""
        ...
