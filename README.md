# Master Paper Trade Lab

Research platform for paper-trading prediction-market strategies. Polymarket-primary, with Kalshi and Deribit as secondary venues for cross-venue and crypto-derivative arbitrage.

> **This is a platform, not a strategy.** It records data, simulates fills rigorously, runs strategies through a 4-stage promotion lifecycle, and surfaces a clean dashboard with multi-dimensional P&L attribution.

See [`DESIGN.md`](./DESIGN.md) for the canonical spec.

## Quick links

- [Platform spec](./DESIGN.md)
- [Strategy template](./src/strategies/_template/)
- [Architecture diagram](./DESIGN.md#9-architecture)
- [Strategy lifecycle gates](./DESIGN.md#2-strategy-lifecycle-the-rigor-model)
- [Realism haircut basis](./DESIGN.md#3-realism-model--the-haircut)

## Status

Phase 0 — scaffolding. No strategies are implemented yet; the platform itself is being built first.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11, asyncio, FastAPI |
| Database | Postgres |
| Frontend | Next.js 14 + shadcn/ui + Tremor + Recharts |
| Hosting | Railway (3 services: worker+API, web, postgres) |
| Budget | ~$35–40/mo |

## Repo structure

```
master-paper-trade-lab/
├── DESIGN.md                  # Canonical spec
├── README.md                  # You are here
├── src/
│   ├── core/                  # Interfaces, events, plugin loader, config system
│   ├── venues/                # MarketDataSource implementations (Polymarket, Kalshi, Deribit, ...)
│   ├── execution/             # FillSimulator implementations (snapshot, event-replay, calibrated)
│   ├── strategies/            # Strategy implementations (one folder per strategy)
│   │   └── _template/         # Template for adding new strategies
│   ├── analytics/
│   │   ├── tags/              # Trade-tagging plugins (one per dimension)
│   │   └── metrics/           # Metric calculators (Sharpe, drawdown, etc.)
│   ├── ground_truth/          # External data adapters (sports, weather, crypto)
│   ├── db/                    # Postgres schema and migrations
│   ├── runner/                # Main async event loop
│   ├── api/                   # FastAPI endpoints for the web UI
│   └── configs/
│       ├── sleeves/           # Per-sleeve YAML configs (one file per sleeve)
│       └── system/            # System-level configs (runtime, pipes, markets)
├── web/                       # Next.js dashboard
├── scripts/                   # Operational scripts (replay, calibration, scaffolding)
├── tests/                     # Unit + integration tests
└── docs/                      # Additional documentation
```

## Adding a new strategy

See [`src/strategies/_template/README.md`](./src/strategies/_template/README.md). Every strategy gets:

- A `DESIGN.md` (12-section research doc)
- A `strategy.py` (implementation)
- One or more `config_*.yaml` (named config bundles)
- A `tests/` folder (synthetic + replay tests)
- A `notes/` folder (observation journal + decision log)

A strategy starts in `replay_only` mode and is promoted through gates: `live_log → live_signal → live_full`.

## License

Private. Not open for distribution.
