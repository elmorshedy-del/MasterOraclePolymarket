"""Resting maker order tracker.

Encapsulates queue-position math for one resting maker order. The fill
simulator owns a dict of these keyed by ``order_id`` and feeds events to
each on every relevant market event.

Conservative model (V1):
  - q_ahead initialized from the order book at placement time
  - Decrement q_ahead by subsequent TRADE_PRINT sizes at-or-through our price
  - Cancels are NOT credited (over-counts queue, makes us slower to fill —
    matches the platform's conservative bias)
  - When q_ahead <= 0 and a trade prints at our price level, we fill
  - If the book moves PAST our price without trades at our level → MISSED

The cancel-decay factor is exposed for future calibration but defaults to
0 (no credit) until Tier 3 calibration data informs us otherwise.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.core.events import (
    Fill,
    FillType,
    MarketEvent,
    Order,
    OrderBook,
    RealismFlag,
    Side,
)

logger = logging.getLogger(__name__)


# Tunable: fraction of cancels we credit toward our queue position.
# Default 0 = the conservative choice. Real-world calibration will lift this.
DEFAULT_CANCEL_DECAY = Decimal("0.0")

# How long after placement we consider a fill "fast" vs "slow"
MAKER_FAST_THRESHOLD_SECS = 10.0


@dataclass
class RestingMaker:
    order: Order
    placed_at: datetime
    placed_book_mid: Decimal | None
    q_ahead: Decimal
    realism_flag: RealismFlag = RealismFlag.CLEAN
    filled_size: Decimal = Decimal(0)
    last_seen_depth_at_price: Decimal = Decimal(0)
    cancel_decay: Decimal = DEFAULT_CANCEL_DECAY

    @property
    def remaining_size(self) -> Decimal:
        return self.order.size - self.filled_size

    @property
    def is_done(self) -> bool:
        return self.remaining_size <= 0

    def process_trade_event(
        self,
        event: MarketEvent,
        book: OrderBook,
    ) -> Fill | None:
        """A TRADE_PRINT happened. If at-or-through our price, decrement queue."""
        try:
            trade_price = Decimal(str(event.payload["price"]))
            trade_size = Decimal(str(event.payload["size"]))
        except (KeyError, ValueError):
            return None

        # For a buy maker (resting bid), trades AT our price or BELOW eat queue.
        # For a sell maker (resting ask), trades AT our price or ABOVE eat queue.
        our_price = self.order.price
        if our_price is None:
            return None

        eats_queue = (
            (self.order.side == Side.BUY and trade_price <= our_price)
            or (self.order.side == Side.SELL and trade_price >= our_price)
        )
        if not eats_queue:
            return None

        # First, depletes queue ahead of us
        if self.q_ahead > 0:
            consumed = min(self.q_ahead, trade_size)
            self.q_ahead -= consumed
            trade_size -= consumed

        if trade_size <= 0 or self.q_ahead > 0:
            return None

        # Queue is now zero — we fill for the remainder of this trade.
        fill_size = min(self.remaining_size, trade_size)
        if fill_size <= 0:
            return None

        self.filled_size += fill_size

        elapsed = (event.ts - self.placed_at).total_seconds()
        fill_type = (
            FillType.MAKER_FAST if elapsed < MAKER_FAST_THRESHOLD_SECS else FillType.MAKER_SLOW
        )

        from uuid import uuid4
        return Fill(
            fill_id=uuid4(),
            order_id=self.order.order_id,
            sleeve_id=self.order.sleeve_id,
            market_id=self.order.market_id,
            asset_id=self.order.asset_id,
            side=self.order.side,
            price=our_price,
            size=fill_size,
            fill_type=fill_type,
            ts_filled=event.ts,
            realism_flag=self.realism_flag,
            metadata={
                "elapsed_secs": elapsed,
                "queue_ahead_at_placement": str(
                    self.q_ahead + self.filled_size
                ),  # rough — for analysis
            },
        )

    def check_walk_away(self, book: OrderBook) -> bool:
        """Has the book moved past our price entirely? Returns True if MISSED."""
        our_price = self.order.price
        if our_price is None:
            return False

        if self.order.side == Side.BUY:
            best_ask = book.best_ask()
            if best_ask is None:
                return False
            # Spread inverted past us means we'd have crossed if still resting.
            # Walk-away: our bid is now far below best ask AND there's no depth
            # at-or-better than our price — i.e., everyone below us was canceled
            # or eaten. Approximation: depth at our price is 0.
            depth = book.depth_at_or_better(Side.BUY, our_price)
            if depth == 0 and best_ask.price > our_price + Decimal("0.05"):
                return True
        else:
            best_bid = book.best_bid()
            if best_bid is None:
                return False
            depth = book.depth_at_or_better(Side.SELL, our_price)
            if depth == 0 and best_bid.price < our_price - Decimal("0.05"):
                return True

        return False

    def to_missed_fill(self, ts: datetime) -> Fill:
        """Emit a 'missed' marker fill with size=0 so position tracker can close out."""
        from uuid import uuid4
        return Fill(
            fill_id=uuid4(),
            order_id=self.order.order_id,
            sleeve_id=self.order.sleeve_id,
            market_id=self.order.market_id,
            asset_id=self.order.asset_id,
            side=self.order.side,
            price=self.order.price or Decimal(0),
            size=Decimal(0),
            fill_type=FillType.MISSED,
            ts_filled=ts,
            realism_flag=self.realism_flag,
            metadata={"reason": "price_walked_away"},
        )
