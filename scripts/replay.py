"""Replay any strategy against recorded data.

Phase 0: stub. Phase 3 implements the full replay engine.

Usage (target):
    python scripts/replay.py --strategy cross_outcome_arb --days 30
    python scripts/replay.py --strategy weather_tail_sell --range 2026-01-01:2026-01-31
    python scripts/replay.py --strategy basket_arb --override latency_ms=100 --days 30
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a strategy against recorded data")
    parser.add_argument("--strategy", required=True, help="Strategy name (folder under src/strategies/)")
    parser.add_argument("--config", default="default", help="Config bundle id")
    parser.add_argument("--days", type=int, help="Replay over the last N days")
    parser.add_argument("--range", help="Replay over an explicit YYYY-MM-DD:YYYY-MM-DD range")
    parser.add_argument(
        "--override",
        action="append",
        default=[],
        help="Parameter override key=value (e.g., latency_ms=100); repeatable",
    )
    args = parser.parse_args()

    print(f"[stub] would replay strategy={args.strategy} config={args.config}")
    print(f"[stub] window: days={args.days} range={args.range}")
    print(f"[stub] overrides: {args.overrides if hasattr(args, 'overrides') else args.override}")
    print("[stub] Phase 3 will implement this. For now, this just validates argparse wiring.")


if __name__ == "__main__":
    main()
