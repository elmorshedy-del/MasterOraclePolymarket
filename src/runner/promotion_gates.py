"""Promotion gate evaluator.

Given a sleeve_id, returns:
  - current mode
  - eligible next mode (or None if already at top / kill-criteria hit)
  - per-criterion pass/fail for the gate to the next mode
  - kill-criteria status

Default criteria match DESIGN.md §2 (the strategy lifecycle). Strategy
authors override per-strategy thresholds in their own DESIGN.md and via
``promotion_overrides`` in the sleeve config (Phase 5+ adds the override
hook; for V1 this evaluator uses platform defaults).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from src.db.connection import get_pool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default thresholds (overridable per strategy in Phase 5+)
# ---------------------------------------------------------------------------


@dataclass
class GateThresholds:
    # replay_only → live_log
    replay_min_signals: int = 30
    replay_min_realized_pnl: Decimal = Decimal("0")
    replay_max_drawdown_pct_of_capital: Decimal = Decimal("0.30")

    # live_log → live_signal
    log_min_days: int = 14
    log_min_signals: int = 30
    log_signal_rate_match_pct: Decimal = Decimal("0.30")  # ±30% of replay rate

    # live_signal → live_full
    signal_min_days: int = 14
    signal_max_implausible_rate: Decimal = Decimal("0.05")
    signal_min_fill_rate: Decimal = Decimal("0.60")

    # live_full ongoing kill criteria
    full_max_dd_pct_of_capital: Decimal = Decimal("0.20")
    full_min_capital_remaining_pct: Decimal = Decimal("0.80")


DEFAULTS = GateThresholds()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CriterionResult:
    name: str
    passed: bool
    actual: float | str | None
    required: float | str | None
    detail: str | None = None


@dataclass
class GateEvaluation:
    sleeve_id: str
    current_mode: str
    next_mode: str | None
    eligible: bool
    criteria: list[CriterionResult] = field(default_factory=list)
    kill_criteria: list[CriterionResult] = field(default_factory=list)
    kill_triggered: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sleeve_id": self.sleeve_id,
            "current_mode": self.current_mode,
            "next_mode": self.next_mode,
            "eligible": self.eligible,
            "criteria": [c.__dict__ for c in self.criteria],
            "kill_criteria": [c.__dict__ for c in self.kill_criteria],
            "kill_triggered": self.kill_triggered,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


_NEXT_MODE = {
    "replay_only": "live_log",
    "live_log": "live_signal",
    "live_signal": "live_full",
    "live_full": None,           # already at top
}


class PromotionEvaluator:
    def __init__(self, thresholds: GateThresholds | None = None) -> None:
        self.thresholds = thresholds or DEFAULTS

    async def evaluate(self, sleeve_id: str) -> GateEvaluation:
        try:
            pool = await get_pool()
        except RuntimeError:
            return GateEvaluation(
                sleeve_id=sleeve_id,
                current_mode="unknown",
                next_mode=None,
                eligible=False,
                notes=["DATABASE_URL not configured"],
            )

        async with pool.acquire() as conn:
            sleeve = await conn.fetchrow(
                """
                SELECT sleeve_id, strategy_name, config_id, edge_class,
                       starting_capital_usd, mode, enabled, started_at
                FROM sleeves
                WHERE sleeve_id = $1
                """,
                sleeve_id,
            )
            if sleeve is None:
                return GateEvaluation(
                    sleeve_id=sleeve_id,
                    current_mode="unknown",
                    next_mode=None,
                    eligible=False,
                    notes=["sleeve not found"],
                )

            current = sleeve["mode"]
            target = _NEXT_MODE.get(current)

            ev = GateEvaluation(
                sleeve_id=sleeve_id,
                current_mode=current,
                next_mode=target,
                eligible=False,
            )

            if current == "live_full":
                # Top of the ladder — only check kill criteria
                await self._check_kill(ev, conn, sleeve)
                ev.eligible = not ev.kill_triggered
                return ev

            if current == "replay_only":
                await self._check_replay_to_log(ev, conn, sleeve)
            elif current == "live_log":
                await self._check_log_to_signal(ev, conn, sleeve)
            elif current == "live_signal":
                await self._check_signal_to_full(ev, conn, sleeve)
            else:
                ev.notes.append(f"unknown mode: {current}")
                return ev

            ev.eligible = all(c.passed for c in ev.criteria)
            return ev

    # ---------------------------------------------------------------------
    # Per-gate checks
    # ---------------------------------------------------------------------

    async def _check_replay_to_log(self, ev: GateEvaluation, conn, sleeve) -> None:
        # Replay must have produced a meaningful number of signals + non-negative PnL
        # We aggregate over recent replay_runs for the same strategy/config
        rows = await conn.fetch(
            """
            SELECT summary FROM replay_runs
            WHERE strategy_name = $1
              AND config_id = $2
              AND status = 'completed'
              AND started_at > now() - interval '60 days'
            ORDER BY started_at DESC
            LIMIT 5
            """,
            sleeve["strategy_name"],
            sleeve["config_id"],
        )
        if not rows:
            ev.criteria.append(CriterionResult(
                name="replay_runs_exist", passed=False,
                actual=0, required="≥1",
                detail="no completed replay_runs for this strategy/config — run a replay first",
            ))
            return

        # Use the most recent run's summary
        summary = rows[0]["summary"] or {}
        if isinstance(summary, str):
            try:
                import orjson
                summary = orjson.loads(summary)
            except Exception:  # noqa: BLE001
                summary = {}

        signals = int(summary.get("signals", 0) or 0)
        realized_str = summary.get("realized_pnl", "0")
        try:
            realized = Decimal(str(realized_str))
        except Exception:  # noqa: BLE001
            realized = Decimal(0)

        # Max drawdown — pull from per-trade ledger for the sleeve(s) that own the run
        dd = await conn.fetchval(
            """
            WITH equity AS (
                SELECT exit_ts, SUM(pnl_after_haircut_usd) OVER (ORDER BY exit_ts) AS cum
                FROM paper_trades
                WHERE strategy_name = $1 AND config_id = $2 AND source = 'replay'
                  AND exit_ts IS NOT NULL
            )
            SELECT MAX(peak - cum) FROM (
                SELECT cum, MAX(cum) OVER (ORDER BY exit_ts) AS peak FROM equity
            ) x
            """,
            sleeve["strategy_name"],
            sleeve["config_id"],
        )
        dd_value = float(dd) if dd is not None else 0.0
        cap = float(sleeve["starting_capital_usd"])
        dd_pct = dd_value / cap if cap > 0 else 0.0

        ev.criteria.extend([
            CriterionResult(
                name="replay_signals",
                passed=signals >= self.thresholds.replay_min_signals,
                actual=signals,
                required=f"≥{self.thresholds.replay_min_signals}",
            ),
            CriterionResult(
                name="replay_realized_pnl",
                passed=realized >= self.thresholds.replay_min_realized_pnl,
                actual=str(realized),
                required=f"≥{self.thresholds.replay_min_realized_pnl}",
            ),
            CriterionResult(
                name="replay_max_drawdown_pct",
                passed=dd_pct <= float(self.thresholds.replay_max_drawdown_pct_of_capital),
                actual=round(dd_pct, 4),
                required=f"≤{float(self.thresholds.replay_max_drawdown_pct_of_capital)}",
            ),
        ])

    async def _check_log_to_signal(self, ev: GateEvaluation, conn, sleeve) -> None:
        days_in_mode = await self._days_since_mode_change(conn, sleeve["sleeve_id"], "live_log")
        live_signals = await conn.fetchval(
            """
            SELECT COUNT(*) FROM signals
            WHERE sleeve_id = $1
              AND ts_signal > now() - interval '30 days'
            """,
            sleeve["sleeve_id"],
        )
        live_signals = int(live_signals or 0)

        # Compare to replay-predicted rate from latest replay run summary
        replay_signals = await self._latest_replay_signals(conn, sleeve)

        rate_match_ok = True
        rate_actual: float | str = "n/a"
        if replay_signals > 0 and days_in_mode > 0:
            replay_per_day = replay_signals / 30.0
            live_per_day = live_signals / max(days_in_mode, 1)
            tolerance = float(self.thresholds.log_signal_rate_match_pct)
            ratio = abs(live_per_day - replay_per_day) / max(replay_per_day, 1e-9)
            rate_match_ok = ratio <= tolerance
            rate_actual = round(ratio, 3)

        ev.criteria.extend([
            CriterionResult(
                name="days_in_live_log",
                passed=days_in_mode >= self.thresholds.log_min_days,
                actual=days_in_mode,
                required=f"≥{self.thresholds.log_min_days}",
            ),
            CriterionResult(
                name="live_log_signals",
                passed=live_signals >= self.thresholds.log_min_signals,
                actual=live_signals,
                required=f"≥{self.thresholds.log_min_signals}",
            ),
            CriterionResult(
                name="signal_rate_matches_replay",
                passed=rate_match_ok,
                actual=rate_actual,
                required=f"deviation ≤ {float(self.thresholds.log_signal_rate_match_pct)}",
            ),
        ])

    async def _check_signal_to_full(self, ev: GateEvaluation, conn, sleeve) -> None:
        days_in_mode = await self._days_since_mode_change(conn, sleeve["sleeve_id"], "live_signal")
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE realism_flag = 'implausible') AS implausible,
                COUNT(*) FILTER (WHERE fill_type IN ('taker', 'maker_fast', 'maker_slow')) AS filled,
                COUNT(*) FILTER (WHERE fill_type = 'missed') AS missed
            FROM paper_fills
            WHERE sleeve_id = $1
              AND ts_filled > now() - interval '30 days'
            """,
            sleeve["sleeve_id"],
        )
        total = int(row["total"] or 0)
        implausible = int(row["implausible"] or 0)
        filled = int(row["filled"] or 0)
        missed = int(row["missed"] or 0)

        impl_rate = implausible / total if total > 0 else 0.0
        fill_rate = filled / (filled + missed) if (filled + missed) > 0 else 0.0

        ev.criteria.extend([
            CriterionResult(
                name="days_in_live_signal",
                passed=days_in_mode >= self.thresholds.signal_min_days,
                actual=days_in_mode,
                required=f"≥{self.thresholds.signal_min_days}",
            ),
            CriterionResult(
                name="implausible_rate",
                passed=impl_rate <= float(self.thresholds.signal_max_implausible_rate),
                actual=round(impl_rate, 4),
                required=f"≤{float(self.thresholds.signal_max_implausible_rate)}",
            ),
            CriterionResult(
                name="fill_rate",
                passed=fill_rate >= float(self.thresholds.signal_min_fill_rate),
                actual=round(fill_rate, 3),
                required=f"≥{float(self.thresholds.signal_min_fill_rate)}",
            ),
        ])

    async def _check_kill(self, ev: GateEvaluation, conn, sleeve) -> None:
        cap = float(sleeve["starting_capital_usd"])

        # Drawdown over the last 30 days
        dd = await conn.fetchval(
            """
            WITH equity AS (
                SELECT ts, capital_remaining FROM sleeve_pnl_snapshots
                WHERE sleeve_id = $1 AND ts > now() - interval '30 days'
                ORDER BY ts ASC
            )
            SELECT MAX(peak - capital_remaining) FROM (
                SELECT capital_remaining, MAX(capital_remaining) OVER (ORDER BY ts) AS peak FROM equity
            ) x
            """,
            sleeve["sleeve_id"],
        )
        dd_value = float(dd) if dd is not None else 0.0
        dd_pct = dd_value / cap if cap > 0 else 0.0

        # Capital remaining ratio
        latest = await conn.fetchval(
            """
            SELECT capital_remaining FROM sleeve_pnl_snapshots
            WHERE sleeve_id = $1
            ORDER BY ts DESC LIMIT 1
            """,
            sleeve["sleeve_id"],
        )
        cap_remaining = float(latest) if latest is not None else cap
        cap_remaining_pct = cap_remaining / cap if cap > 0 else 1.0

        kill_dd = dd_pct > float(self.thresholds.full_max_dd_pct_of_capital)
        kill_cap = cap_remaining_pct < float(self.thresholds.full_min_capital_remaining_pct)

        ev.kill_criteria.extend([
            CriterionResult(
                name="drawdown_within_limit",
                passed=not kill_dd,
                actual=round(dd_pct, 4),
                required=f"≤{float(self.thresholds.full_max_dd_pct_of_capital)}",
            ),
            CriterionResult(
                name="capital_remaining_above_floor",
                passed=not kill_cap,
                actual=round(cap_remaining_pct, 4),
                required=f"≥{float(self.thresholds.full_min_capital_remaining_pct)}",
            ),
        ])
        ev.kill_triggered = kill_dd or kill_cap

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------

    async def _days_since_mode_change(self, conn, sleeve_id: str, target_mode: str) -> int:
        ts = await conn.fetchval(
            """
            SELECT changed_at FROM sleeve_mode_history
            WHERE sleeve_id = $1 AND to_mode = $2
            ORDER BY changed_at DESC LIMIT 1
            """,
            sleeve_id,
            target_mode,
        )
        if ts is None:
            # Fall back to sleeve start; if the sleeve was created in the
            # target mode, sleeve_mode_history may have no row.
            ts = await conn.fetchval(
                "SELECT started_at FROM sleeves WHERE sleeve_id = $1",
                sleeve_id,
            )
        if ts is None:
            return 0
        return max(0, (datetime.now(tz=timezone.utc) - ts).days)

    async def _latest_replay_signals(self, conn, sleeve) -> int:
        row = await conn.fetchrow(
            """
            SELECT summary FROM replay_runs
            WHERE strategy_name = $1 AND config_id = $2 AND status = 'completed'
            ORDER BY started_at DESC LIMIT 1
            """,
            sleeve["strategy_name"],
            sleeve["config_id"],
        )
        if row is None or row["summary"] is None:
            return 0
        summary = row["summary"]
        if isinstance(summary, str):
            try:
                import orjson
                summary = orjson.loads(summary)
            except Exception:  # noqa: BLE001
                summary = {}
        return int(summary.get("signals", 0) or 0)
