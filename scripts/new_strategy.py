"""Scaffold a new strategy folder under src/strategies/<name>/.

Usage:
    python scripts/new_strategy.py <strategy_name> [--edge-class CLASS]

Creates the canonical layout:

    src/strategies/<name>/
        __init__.py
        DESIGN.md          (filled from the template, with strategy name + edge class)
        strategy.py        (skeleton implementing the Strategy protocol)
        config_default.yaml
        notes/
            observations.md
            decisions.md
        tests/
            __init__.py
            test_synthetic.py   (one trivial passing test, ready to grow)
            test_replay.py      (DB-gated, skips if no events)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from textwrap import dedent

REPO_ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = REPO_ROOT / "src" / "strategies"
TEMPLATE_DIR = STRATEGIES / "_template"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="strategy slug (snake_case, no leading underscore)")
    ap.add_argument("--edge-class", default="directional",
                    choices=["pure_arb", "maker", "latency_sensitive",
                             "directional", "copy", "tail", "slow"])
    args = ap.parse_args()

    name: str = args.name.strip().lower().replace("-", "_")
    if not name or name.startswith("_") or " " in name:
        print(f"invalid strategy name: {name!r}", file=sys.stderr)
        return 1

    target = STRATEGIES / name
    if target.exists():
        print(f"strategy folder already exists: {target}", file=sys.stderr)
        return 1

    target.mkdir(parents=True)
    (target / "notes").mkdir()
    (target / "tests").mkdir()

    (target / "__init__.py").write_text("")
    (target / "tests" / "__init__.py").write_text("")
    (target / "notes" / "observations.md").write_text(dedent(f"""\
        # {name} — Live Observation Journal

        Append-only log of what we observe in production.
        """))
    (target / "notes" / "decisions.md").write_text(dedent(f"""\
        # {name} — Decision Log

        Append-only record of design + parameter decisions, with rationale.
        """))

    # DESIGN.md from template
    template = (TEMPLATE_DIR / "DESIGN.md.template").read_text()
    design = template.replace("<STRATEGY_NAME>", name)
    (target / "DESIGN.md").write_text(design)

    # strategy.py skeleton
    (target / "strategy.py").write_text(dedent(f'''\
        """{name} — TODO: thesis sentence.

        See ``DESIGN.md`` in this folder for the full specification.
        """

        from __future__ import annotations

        from typing import Any

        from src.core.events import EventType, MarketEvent, Signal


        class {_to_class(name)}:
            name: str = "{name}"
            edge_class: str = "{args.edge_class}"

            def required_event_types(self) -> set[str]:
                return {{EventType.BOOK_SNAPSHOT.value, EventType.BOOK_DELTA.value}}

            def required_data_sources(self) -> set[str]:
                return {{"polymarket_clob"}}

            async def on_event(self, event: MarketEvent, state: dict[str, Any]) -> list[Signal]:
                # TODO: implement signal generation
                return []


        def plugin() -> {_to_class(name)}:
            return {_to_class(name)}()
    '''))

    # config_default.yaml
    (target / "config_default.yaml").write_text(dedent(f"""\
        name: default
        description: |
          Default configuration for {name}.

        params: {{}}
        """))

    # tests
    (target / "tests" / "test_synthetic.py").write_text(dedent(f'''\
        """Synthetic-event tests for {name}."""

        from __future__ import annotations

        import pytest

        from src.strategies.{name}.strategy import {_to_class(name)}


        @pytest.mark.asyncio
        async def test_strategy_loads():
            strat = {_to_class(name)}()
            assert strat.name == "{name}"
            assert strat.edge_class
    '''))

    (target / "tests" / "test_replay.py").write_text(dedent(f'''\
        """Replay validation for {name}.

        Skips if DATABASE_URL is unset (so this test passes on a fresh checkout).
        """

        from __future__ import annotations

        import os
        from datetime import datetime, timedelta, timezone
        from decimal import Decimal

        import pytest

        from src.runner.replay_engine import ReplayEngine, ReplayOverrides


        @pytest.mark.asyncio
        async def test_replay_smoke():
            if not os.environ.get("DATABASE_URL"):
                pytest.skip("no DATABASE_URL")
            end = datetime.now(tz=timezone.utc)
            engine = ReplayEngine()
            await engine.run(
                strategy_name="{name}",
                config_id="default",
                range_start=end - timedelta(days=7),
                range_end=end,
                starting_capital=Decimal("5000"),
                edge_class="{args.edge_class}",
                overrides=ReplayOverrides(),
            )
    '''))

    print(f"created {target.relative_to(REPO_ROOT)}")
    print()
    print("Next steps:")
    print(f"  1. Fill in {target.relative_to(REPO_ROOT)}/DESIGN.md (12 sections)")
    print(f"  2. Implement {target.relative_to(REPO_ROOT)}/strategy.py")
    print(f"  3. Tune {target.relative_to(REPO_ROOT)}/config_default.yaml")
    print(f"  4. Run synthetic tests:  pytest src/strategies/{name}/tests/test_synthetic.py")
    print(f"  5. Register a sleeve YAML at src/configs/sleeves/{name}__default.yaml")
    return 0


def _to_class(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_")) or "Strategy"


if __name__ == "__main__":
    raise SystemExit(main())
