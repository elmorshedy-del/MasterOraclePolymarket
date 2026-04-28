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

1. Copy this `_template/` folder to `src/strategies/<your_name>/`
2. Fill in `DESIGN.md` — every section is required before code is written
3. Implement `strategy.py` (use `strategy_template.py` here as the starting point)
4. Write synthetic tests
5. Run replay against last 30 days: `python scripts/replay.py --strategy <your_name> --days 30`
6. If replay passes, set the sleeve config's `mode: live_log` and observe for 1–2 weeks
7. Promote through `live_signal` → `live_full` per gate criteria in your `DESIGN.md`

## DESIGN.md template

Use `DESIGN.md.template` in this folder as the starting point. The 12 sections:

1. Thesis (one sentence)
2. Mechanics (precise math/predicates)
3. Data dependencies (every feed and market filter)
4. Entry rules (predicates with examples)
5. Exit rules (TP, stop, time, resolution)
6. Sizing logic
7. Risk rules (concurrent, per-market, correlated)
8. Failure modes (loss conditions + real-time detection)
9. References (academic, industry, scout findings)
10. Validation plan (synthetic, replay, live observation)
11. Promotion criteria (numbers required to advance)
12. Kill criteria (numbers that trigger shutdown)

## Promotion gates (default — strategy `DESIGN.md` may tighten)

| Gate | Required to pass |
|---|---|
| `replay_only` → `live_log` | ≥50 signals in 30-day replay; replay Sharpe > 0; max DD < 30% of $5k notional |
| `live_log` → `live_signal` | After 1–2 weeks live: ≥30 live signals; signal rate matches replay ±25% |
| `live_signal` → `live_full` | After 1–2 weeks: simulated fill rate matches model; no `realism_flag = implausible` rate >5% |
| `live_full` ongoing | Kill if 30-day Sharpe drops below own threshold OR realism flags spike OR P&L < own kill line |
