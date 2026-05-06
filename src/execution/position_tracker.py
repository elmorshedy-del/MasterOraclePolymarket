"""Per-sleeve position and P&L tracker.

Consumes Fills, maintains positions per (sleeve, market, asset, side), and
emits Trade rows when a position closes.

Algorithm (V1 — simple averaging):
  - Same-side fills add to position; avg_entry is size-weighted average.
  - Opposite-side fills close (or partially close) the position.
  - On full close, emit a Trade with realized P&L.
  - On partial close, emit a Trade for the closed portion; remainder stays open.

P&L calc per Polymarket binary semantics:
  - For a YES holder closing at exit: pnl = (exit_price - entry_price) * size
  - For a NO holder (i.e., bought "no" outcome at price p): pnl = same formula,
    where price represents probability-of-the-outcome the position represents.
  - Gas costs subtracted from pnl per fill.

Note: redemption-at-resolution is a separate code path (Phase 4).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from src.core.config import HaircutConfig
from src.core.events import (
    Fill,
    FillType,
    RealismFlag,
    Side,
    Trade,
)

logger = logging.getLogger(__name__)


@dataclass
class Position:
    sleeve_id: str
    market_id: str
    asset_id: str
    side: Side                  # the direction the holder is long
    size: Decimal
    avg_entry: Decimal
    opened_at: datetime
    last_updated: datetime
    total_gas_paid: Decimal = Decimal(0)
    # Size-weighted average slippage_bps across all entry fills. Used to
    # propagate the entry-side slippage cost into the Trade row when the
    # position eventually closes.
    weighted_entry_slippage_bps: Decimal = Decimal(0)


@dataclass
class SleevePnL:
    sleeve_id: str
    realized: Decimal = Decimal(0)
    unrealized: Decimal = Decimal(0)
    capital_remaining: Decimal = Decimal(0)
    open_position_count: int = 0


class PositionTracker:
    def __init__(
        self,
        sleeve_starting_capital: dict[str, Decimal] | None = None,
        haircut: HaircutConfig | None = None,
        edge_class_by_sleeve: dict[str, str] | None = None,
    ) -> None:
        self._positions: dict[tuple[str, str, str, Side], Position] = {}
        self._starting_capital: dict[str, Decimal] = dict(sleeve_starting_capital or {})
        self._realized: dict[str, Decimal] = {}
        self._gas_paid: dict[str, Decimal] = {}
        self._haircut = haircut or HaircutConfig()
        self._edge_class_by_sleeve = dict(edge_class_by_sleeve or {})

        self.trades_emitted: int = 0

    # -----------------------------------------------------------------------
    # Sleeve registration
    # -----------------------------------------------------------------------

    def register_sleeve(
        self,
        sleeve_id: str,
        starting_capital: Decimal,
        edge_class: str | None = None,
    ) -> None:
        self._starting_capital[sleeve_id] = starting_capital
        self._realized.setdefault(sleeve_id, Decimal(0))
        self._gas_paid.setdefault(sleeve_id, Decimal(0))
        if edge_class is not None:
            self._edge_class_by_sleeve[sleeve_id] = edge_class

    # -----------------------------------------------------------------------
    # Fill consumption
    # -----------------------------------------------------------------------

    def on_fill(
        self,
        fill: Fill,
        strategy_name: str,
        config_id: str,
        config_hash: str,
    ) -> Trade | None:
        """Apply a fill. Returns a Trade if a position closed (fully or partially)."""
        if fill.fill_type == FillType.MISSED or fill.size <= 0:
            return None

        # The "long" side of the position is the side we BOUGHT.
        long_side = fill.side
        key_buy = (fill.sleeve_id, fill.market_id, fill.asset_id, Side.BUY)
        key_sell = (fill.sleeve_id, fill.market_id, fill.asset_id, Side.SELL)

        # Track gas
        self._gas_paid[fill.sleeve_id] = (
            self._gas_paid.get(fill.sleeve_id, Decimal(0)) + fill.gas_cost
        )

        # Same-side existing position → add. Opposite-side → close.
        same_key = key_buy if long_side == Side.BUY else key_sell
        opp_key = key_sell if long_side == Side.BUY else key_buy

        existing = self._positions.get(same_key)
        opp = self._positions.get(opp_key)

        if opp is not None:
            # Closing a position
            return self._close_against(
                fill, opp, opp_key, strategy_name, config_id, config_hash
            )

        # Adding to (or opening) same-side position
        fill_slip = fill.slippage_bps if fill.slippage_bps is not None else Decimal(0)
        if existing is None:
            self._positions[same_key] = Position(
                sleeve_id=fill.sleeve_id,
                market_id=fill.market_id,
                asset_id=fill.asset_id,
                side=long_side,
                size=fill.size,
                avg_entry=fill.price,
                opened_at=fill.ts_filled,
                last_updated=fill.ts_filled,
                total_gas_paid=fill.gas_cost,
                weighted_entry_slippage_bps=fill_slip,
            )
        else:
            new_size = existing.size + fill.size
            existing.avg_entry = (
                (existing.avg_entry * existing.size + fill.price * fill.size) / new_size
            )
            # Size-weighted average of slippage across all entry fills.
            existing.weighted_entry_slippage_bps = (
                (existing.weighted_entry_slippage_bps * existing.size + fill_slip * fill.size)
                / new_size
            )
            existing.size = new_size
            existing.last_updated = fill.ts_filled
            existing.total_gas_paid += fill.gas_cost

        return None

    # -----------------------------------------------------------------------
    # Resolution / redemption
    # -----------------------------------------------------------------------

    def redeem_market(
        self,
        market_id: str,
        winning_asset_id: str | None,
        ts,
        strategy_name: str = "",
        config_id: str = "default",
        config_hash: str = "resolution",
    ) -> list[Trade]:
        """Settle every open position on ``market_id`` at resolution prices.

        Polymarket resolution semantics:
          - Winning asset's tokens redeem to $1.00
          - Every other asset's tokens redeem to $0.00

        Emits a Trade per closed position tagged with the resolution price as
        exit_price. Removes positions from the in-memory tracker.

        If ``winning_asset_id`` is None we know the market resolved but not
        which side won — close at avg_entry (no PnL impact) so the platform
        is consistent and the strategy can re-fire on subsequent markets.
        """
        affected = [
            (key, pos) for (key, pos) in list(self._positions.items())
            if pos.market_id == market_id
        ]
        trades: list[Trade] = []
        for key, pos in affected:
            if winning_asset_id is None:
                exit_price = pos.avg_entry
            elif pos.asset_id == winning_asset_id:
                exit_price = Decimal("1") if pos.side == Side.BUY else Decimal("0")
            else:
                exit_price = Decimal("0") if pos.side == Side.BUY else Decimal("1")

            if pos.side == Side.BUY:
                raw = (exit_price - pos.avg_entry) * pos.size
            else:
                raw = (pos.avg_entry - exit_price) * pos.size
            raw -= pos.total_gas_paid

            edge_class = self._edge_class_by_sleeve.get(pos.sleeve_id)
            haircut = (
                self._haircut.overrides_by_edge_class.get(edge_class, self._haircut.default)
                if edge_class is not None else self._haircut.default
            )
            pnl_after = raw * (Decimal(1) - haircut)

            self._realized[pos.sleeve_id] = (
                self._realized.get(pos.sleeve_id, Decimal(0)) + raw
            )

            trades.append(Trade(
                trade_id=uuid4(),
                sleeve_id=pos.sleeve_id,
                strategy_name=strategy_name,
                config_id=config_id,
                market_id=pos.market_id,
                asset_id=pos.asset_id,
                side=pos.side,
                entry_price=pos.avg_entry,
                entry_size=pos.size,
                entry_ts=pos.opened_at,
                exit_price=exit_price,
                exit_size=pos.size,
                exit_ts=ts,
                pnl=raw,
                pnl_after_haircut=pnl_after,
                realism_flag=RealismFlag.CLEAN,
                fill_type=FillType.TAKER,   # resolution settlement; no maker queue involvement
                tags={"config_hash": config_hash, "edge_class": edge_class, "settlement": True},
            ))
            del self._positions[key]
            self.trades_emitted += 1
        return trades

    def _close_against(
        self,
        fill: Fill,
        position: Position,
        position_key: tuple[str, str, str, Side],
        strategy_name: str,
        config_id: str,
        config_hash: str,
    ) -> Trade:
        """Close (or partially close) ``position`` against an opposing-side fill."""
        close_size = min(position.size, fill.size)
        # P&L for closing direction depends on which side held the position
        if position.side == Side.BUY:
            pnl = (fill.price - position.avg_entry) * close_size
        else:
            pnl = (position.avg_entry - fill.price) * close_size

        # Subtract gas attributable to closed portion (proportional)
        attributable_gas = position.total_gas_paid * (close_size / position.size) + fill.gas_cost
        pnl -= attributable_gas

        # Apply per-sleeve haircut for display-only field
        edge_class = self._edge_class_by_sleeve.get(fill.sleeve_id)
        haircut = (
            self._haircut.overrides_by_edge_class.get(edge_class, self._haircut.default)
            if edge_class is not None
            else self._haircut.default
        )
        pnl_after = pnl * (Decimal(1) - haircut)

        # Update realized
        self._realized[fill.sleeve_id] = (
            self._realized.get(fill.sleeve_id, Decimal(0)) + pnl
        )

        # Update position state
        position.size -= close_size
        position.total_gas_paid -= position.total_gas_paid * (close_size / (position.size + close_size))
        position.last_updated = fill.ts_filled
        if position.size <= 0:
            del self._positions[position_key]

        # Average entry-side slippage (already size-weighted on the position)
        # plus this exit-fill's slippage, weighted across both legs.
        exit_slip = fill.slippage_bps if fill.slippage_bps is not None else Decimal(0)
        avg_slippage_bps = (
            (position.weighted_entry_slippage_bps + exit_slip) / Decimal(2)
        ).quantize(Decimal("0.01"))

        trade = Trade(
            trade_id=uuid4(),
            sleeve_id=fill.sleeve_id,
            strategy_name=strategy_name,
            config_id=config_id,
            market_id=fill.market_id,
            asset_id=fill.asset_id,
            side=position.side,
            entry_price=position.avg_entry,
            entry_size=close_size,
            entry_ts=position.opened_at,
            exit_price=fill.price,
            exit_size=close_size,
            exit_ts=fill.ts_filled,
            pnl=pnl,
            pnl_after_haircut=pnl_after,
            realism_flag=fill.realism_flag,
            fill_type=fill.fill_type,
            slippage_bps=avg_slippage_bps,
            tags={
                "config_hash": config_hash,
                "edge_class": edge_class,
            },
        )

        # If there's leftover size on the closing fill, that size opens a new
        # position on the closing side.
        leftover = fill.size - close_size
        if leftover > 0:
            opp_key = (fill.sleeve_id, fill.market_id, fill.asset_id, fill.side)
            self._positions[opp_key] = Position(
                sleeve_id=fill.sleeve_id,
                market_id=fill.market_id,
                asset_id=fill.asset_id,
                side=fill.side,
                size=leftover,
                avg_entry=fill.price,
                opened_at=fill.ts_filled,
                last_updated=fill.ts_filled,
                total_gas_paid=fill.gas_cost,
            )

        self.trades_emitted += 1
        return trade

    # -----------------------------------------------------------------------
    # Reads
    # -----------------------------------------------------------------------

    def positions(self, sleeve_id: str | None = None) -> list[Position]:
        if sleeve_id is None:
            return list(self._positions.values())
        return [p for p in self._positions.values() if p.sleeve_id == sleeve_id]

    def pnl(
        self,
        sleeve_id: str,
        mark_prices: dict[tuple[str, str], Decimal] | None = None,
    ) -> SleevePnL:
        starting = self._starting_capital.get(sleeve_id, Decimal(0))
        realized = self._realized.get(sleeve_id, Decimal(0))

        unrealized = Decimal(0)
        open_count = 0
        for pos in self._positions.values():
            if pos.sleeve_id != sleeve_id:
                continue
            open_count += 1
            if mark_prices is None:
                continue
            mark = mark_prices.get((pos.market_id, pos.asset_id))
            if mark is None:
                continue
            if pos.side == Side.BUY:
                unrealized += (mark - pos.avg_entry) * pos.size
            else:
                unrealized += (pos.avg_entry - mark) * pos.size

        return SleevePnL(
            sleeve_id=sleeve_id,
            realized=realized,
            unrealized=unrealized,
            capital_remaining=starting + realized,
            open_position_count=open_count,
        )

    def all_sleeve_ids(self) -> list[str]:
        return list(self._starting_capital.keys())
