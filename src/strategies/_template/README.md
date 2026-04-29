# Strategy Template

Every strategy lives in its own folder under `src/strategies/<name>/`. The folder structure:

```
<strategy_name>/
├── DESIGN.md             # The 12-section research doc (REQUIRED)
├── strategy.py           # Implementation — exports `plugin()` factory
├── config_default.yaml   # The default config bundle
├── config_*.yaml         # Additional named bundles (aggressive, conservative, etc.)
├── tests/
│   ├── test_synthetic.py # Synthetic event tests (REQUIRED before promotion)
│   └── test_replay.py    # 30-day replay assertions (REQUIRED for live_log)
└── notes/
    ├── observations.md   # Live observation journal
    └── decisions.md      # Why config X vs Y, why promoted, why killed
```

## Adding a new strategy

```bash
python scripts/new_strategy.py <name> --edge-class pure_arb
```

The scaffolder produces a working skeleton. Your job:

1. Fill in `DESIGN.md` — every section is required before code is written
2. Implement `strategy.py`
3. Tune the default config
4. Write synthetic tests covering entry / exit / boundary / negative cases
5. Run the replay test against last 30 days: `pytest src/strategies/<name>/tests/`
6. Register a sleeve YAML at `src/configs/sleeves/<name>__default.yaml`
7. Set `mode: replay_only` initially — the system will auto-promote through gates

## Reference: cross_outcome_arb

`src/strategies/cross_outcome_arb/` is the canonical reference. Use it as a worked example for:

- Replay-deterministic state (book maintained per-asset from MarketEvents, not from STORE)
- Multi-leg signal emission (paired BUY signals share metadata for downstream attribution)
- Active-arb tracking in `state` to avoid stacking (`active_arbs: set[market_id]`)
- Conservative buffering (`price_buffer_bps` over the ask) to ensure realistic fills
- Edge-class haircut (`pure_arb` → −18% override)

## DESIGN.md template

Use `DESIGN.md.template` in this folder as the starting point. The 12 sections:

1. **Thesis** (one sentence)
2. **Mechanics** (precise math/predicates)
3. **Data dependencies** (every feed and market filter)
4. **Entry rules** (predicates with examples)
5. **Exit rules** (TP, stop, time, resolution)
6. **Sizing logic**
7. **Risk rules** (concurrent, per-market, correlated)
8. **Failure modes** (loss conditions + real-time detection)
9. **References** (academic, industry, scout findings)
10. **Validation plan** (synthetic, replay, live observation)
11. **Promotion criteria** (numbers required to advance)
12. **Kill criteria** (numbers that trigger shutdown)

## Promotion gates (default — strategy `DESIGN.md` may tighten)

The platform evaluates these via `src/runner/promotion_gates.py` and surfaces the result on the Sleeve Detail page.

| Gate | Required to pass |
|---|---|
| `replay_only` → `live_log` | ≥30 signals in 30-day replay; replay realized PnL > 0; max DD < 30% of capital |
| `live_log` → `live_signal` | ≥14 days live; ≥30 live signals; live signal rate within ±30% of replay-predicted |
| `live_signal` → `live_full` | ≥14 days; implausible rate ≤5%; fill rate ≥60% |
| `live_full` ongoing kill | DD > 20% of capital OR capital_remaining < 80% of starting |

Per-strategy overrides come in Phase 5+; for V1 platform defaults apply.
