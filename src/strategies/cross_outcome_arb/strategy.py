"""cross_outcome_arb — buy YES + NO on the same binary market when their
ask-sum is below $1.00.

See ``DESIGN.md`` in this folder for the full specification.

Replay-deterministic: the strategy maintains its own in-state book per
asset_id, derived purely from MarketEvents. No reliance on the platform's
shared OrderBookStore so live and replay paths produce identical signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import uuid4

from src.core.events import (
    EventType,
    MarketEvent,
    OrderType,
    Side,
    Signal,
)


# ---------------------------------------------------------------------------
# Tunable params (overridden via sleeve YAML)
# ---------------------------------------------------------------------------


@dataclass
class CrossOutcomeArbParams:
    min_edge_bps: int = 100              # require ≥1.00% gross edge before signaling
    max_sum_threshold: Decimal = Decimal("0.99")
    max_size_per_leg_usd: Decimal = Decimal("200")
    price_buffer_bps: int = 50           # overshoot the ask by 0.50¢ to ensure fill
    max_concurrent_positions: int = 25


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class CrossOutcomeArb:
    """The reference strategy for the platform.

    Subscribes to BOOK_SNAPSHOT and BOOK_DELTA events on Polymarket, maintains
    a per-asset best-ask projection in ``state``, fires paired BUY signals
    when the sum across both legs of a binary market drops below the
    configured threshold.
    """

    name: str = "cross_outcome_arb"
    edge_class: str = "pure_arb"

    def __init__(self, **params: Any) -> None:
        self.params = CrossOutcomeArbParams(
            **{k: v for k, v in params.items() if k in CrossOutcomeArbParams.__annotations__},
        )
        # coerce decimal fields
        if not isinstance(self.params.max_sum_threshold, Decimal):
            self.params.max_sum_threshold = Decimal(str(self.params.max_sum_threshold))
        if not isinstance(self.params.max_size_per_leg_usd, Decimal):
            self.params.max_size_per_leg_usd = Decimal(str(self.params.max_size_per_leg_usd))

    # ----------------------------------------------------------------------
    # Strategy protocol
    # ----------------------------------------------------------------------

    def required_event_types(self) -> set[str]:
        return {EventType.BOOK_SNAPSHOT.value, EventType.BOOK_DELTA.value}

    def required_data_sources(self) -> set[str]:
        return {"polymarket_clob"}

    async def on_event(
        self,
        event: MarketEvent,
        state: dict[str, Any],
    ) -> list[Signal]:
        if event.event_type not in (EventType.BOOK_SNAPSHOT, EventType.BOOK_DELTA):
            return []
        if event.venue != "polymarket":
            return []
        if event.market_id is None or event.asset_id is None:
            return []

        books: dict[str, dict[str, Any]] = state.setdefault("books", {})
        market_to_assets: dict[str, set[str]] = state.setdefault("market_assets", {})
        active_arbs: set[str] = state.setdefault("active_arbs", set())

        # Maintain per-asset book
        if event.event_type == EventType.BOOK_SNAPSHOT:
            asks = _parse_asks(event.payload)
            book = books.setdefault(event.asset_id, {})
            book["asks"] = asks   # sorted ascending
            book["market_id"] = event.market_id
            market_to_assets.setdefault(event.market_id, set()).add(event.asset_id)
        else:
            book = books.get(event.asset_id)
            if book is None:
                return []  # haven't seen a snapshot for this asset yet
            _apply_delta(book, event.payload)

        # Check arb only for binary markets — exactly 2 known assets
        assets = market_to_assets.get(event.market_id, set())
        if len(assets) != 2:
            return []

        # Skip if we already have an active arb on this market
        if event.market_id in active_arbs:
            return []

        # Risk cap
        if len(active_arbs) >= self.params.max_concurrent_positions:
            return []

        asset_a, asset_b = sorted(assets)  # deterministic ordering
        book_a = books.get(asset_a)
        book_b = books.get(asset_b)
        if book_a is None or book_b is None:
            return []

        ask_a = _best_ask(book_a)
        ask_b = _best_ask(book_b)
        if ask_a is None or ask_b is None:
            return []

        sum_asks = ask_a + ask_b
        if sum_asks > self.params.max_sum_threshold:
            return []

        gross_edge_bps = int((Decimal("1") - sum_asks) * Decimal("10000"))
        if gross_edge_bps < self.params.min_edge_bps:
            return []

        # Build the two signals
        size_a = self._compute_size(ask_a)
        size_b = self._compute_size(ask_b)
        if size_a <= 0 or size_b <= 0:
            return []

        buffer = Decimal(self.params.price_buffer_bps) / Decimal("10000")
        price_a = (ask_a + buffer).quantize(Decimal("0.0001"))
        price_b = (ask_b + buffer).quantize(Decimal("0.0001"))

        active_arbs.add(event.market_id)

        reason = (
            f"cross_outcome_arb: sum_asks={sum_asks:.4f} "
            f"edge_bps={gross_edge_bps} "
            f"a={asset_a[:8]}@{ask_a:.4f} b={asset_b[:8]}@{ask_b:.4f}"
        )

        sleeve_id = state.get("sleeve_id", "")
        config_id = state.get("config_id", "default")

        return [
            Signal(
                signal_id=uuid4(),
                sleeve_id=sleeve_id,
                strategy_name=self.name,
                config_id=config_id,
                market_id=event.market_id,
                asset_id=asset_a,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                price=price_a,
                size=size_a,
                reason=reason,
                ts_signal=event.ts,
                metadata={"leg": "a", "paired_asset_id": asset_b, "gross_edge_bps": gross_edge_bps},
            ),
            Signal(
                signal_id=uuid4(),
                sleeve_id=sleeve_id,
                strategy_name=self.name,
                config_id=config_id,
                market_id=event.market_id,
                asset_id=asset_b,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                price=price_b,
                size=size_b,
                reason=reason,
                ts_signal=event.ts,
                metadata={"leg": "b", "paired_asset_id": asset_a, "gross_edge_bps": gross_edge_bps},
            ),
        ]

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------

    def _compute_size(self, ask: Decimal) -> Decimal:
        if ask <= 0:
            return Decimal(0)
        target = self.params.max_size_per_leg_usd
        return (target / ask).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Book parsing helpers
# ---------------------------------------------------------------------------


def _parse_asks(payload: dict[str, Any]) -> list[tuple[Decimal, Decimal]]:
    raw = payload.get("asks") or []
    out: list[tuple[Decimal, Decimal]] = []
    for level in raw:
        try:
            price = Decimal(str(level["price"]))
            size = Decimal(str(level["size"]))
        except (KeyError, ValueError):
            continue
        if size > 0:
            out.append((price, size))
    out.sort(key=lambda x: x[0])
    return out


def _apply_delta(book: dict[str, Any], payload: dict[str, Any]) -> None:
    asks: list[tuple[Decimal, Decimal]] = book.setdefault("asks", [])
    for ch in payload.get("changes", []):
        try:
            side = ch.get("side", "").lower()
            price = Decimal(str(ch["price"]))
            size = Decimal(str(ch["size"]))
        except (KeyError, ValueError):
            continue
        # We only care about asks for arb detection; bid changes ignored.
        if side != "sell":
            continue
        # Set absolute size at the price level
        for i, (p, _s) in enumerate(asks):
            if p == price:
                if size <= 0:
                    asks.pop(i)
                else:
                    asks[i] = (price, size)
                break
        else:
            if size > 0:
                asks.append((price, size))
    asks.sort(key=lambda x: x[0])


def _best_ask(book: dict[str, Any]) -> Decimal | None:
    asks: list[tuple[Decimal, Decimal]] = book.get("asks") or []
    return asks[0][0] if asks else None


# ---------------------------------------------------------------------------
# Plugin factory
# ---------------------------------------------------------------------------


def plugin() -> CrossOutcomeArb:
    return CrossOutcomeArb()
