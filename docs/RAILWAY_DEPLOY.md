# Railway deployment

Three services (+ Postgres):

| Service | Image | Start command | Notes |
|---|---|---|---|
| `worker` | `Dockerfile` (root) | `python -m src.runner.main` | Long-lived async process. No HTTP. |
| `api` | `Dockerfile` (root) | `uvicorn src.api.main:app --host 0.0.0.0 --port $PORT` | Public — dashboard backend. |
| `web` | `web/Dockerfile` | `npm run start` | Public — Next.js dashboard. |
| `postgres` | Railway plugin | — | Provisioned via Railway. |

The `worker` and `api` are the **same Python codebase** but different start
commands. They share the database. In V1 they can be one service if budget
needs it (the API surface is small); the split keeps options open for scaling.

## Environment variables (per service)

All three Python services need:

```
DATABASE_URL=postgresql+asyncpg://...
LOG_LEVEL=INFO
POLYMARKET_CLOB_WS_URL=wss://ws-subscriptions-clob.polymarket.com/ws/market
POLYMARKET_DATA_API_URL=https://data-api.polymarket.com
```

`web` needs:

```
BACKEND_URL=https://<api-service-name>.up.railway.app
```

Optional (only if the corresponding pipe is enabled in `pipes.yaml`):

```
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=
KALSHI_API_BASE=
DERIBIT_WS_URL=
```

## Cost target (V1)

| Service | Estimate |
|---|---|
| worker | ~$15–20/mo (1 vCPU, 1 GB) |
| api | ~$3–5/mo (small, usage-based) |
| web | ~$3–5/mo (sleeps when idle) |
| postgres | ~$10/mo (mid-tier, ~5–8 GB target) |
| **Total** | **~$30–40/mo** |

To collapse costs further, merge `worker` and `api` into a single service
(uvicorn running the FastAPI app, with the runner's async loop launched in
a startup event). This trades architectural cleanliness for ~$5/mo. V1
defaults to split.

## First-time setup

1. `railway login` and `railway link <project>`
2. Create three services from this repo (worker, api, web). Web uses `web/Dockerfile`.
3. Add a Postgres plugin; copy its `DATABASE_URL` to the Python services.
4. Set the start commands per the table above.
5. Add env vars per service.
6. Run the schema migration: `psql $DATABASE_URL -f src/db/schema.sql`
7. Deploy.

The `worker` will boot, log a Phase-0 summary, and idle until Phase 1 fleshes
out the ingestion loop.
