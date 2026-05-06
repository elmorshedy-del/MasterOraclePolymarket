# Railway deployment runbook

This repo deploys as **three Railway services** sharing one Postgres plugin.
All three Python services use the same Docker image — the role is selected
by the `RUN_MODE` env var.

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  api service     │    │  worker service  │    │  web service     │
│  RUN_MODE=api    │    │  RUN_MODE=worker │    │  Next.js dash    │
│  Dockerfile      │    │  Dockerfile      │    │  web/Dockerfile  │
└────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘
         │                       │                       │
         └───────────────┬───────┘                       │
                         ▼                               │
                ┌──────────────────┐                     │
                │ Postgres plugin  │◄────────────────────┘
                │ (Railway-managed)│  (web hits api, api hits db)
                └──────────────────┘
```

---

## Order of operations on Railway

### 1. Create the Postgres plugin first

In your Railway project, **New → Database → PostgreSQL**. This auto-creates
a `DATABASE_URL` env var that you can reference from each service.

### 2. Create the API service

- **New → GitHub Repo** (this repo)
- Service settings → **Build → Dockerfile** → keep as `Dockerfile` (root)
- **Variables**:
  - `DATABASE_URL` — link to the Postgres plugin (Railway: `${{ Postgres.DATABASE_URL }}`)
  - `RUN_MODE=api`
  - `PORT` — Railway injects automatically; do NOT override
- **Settings → Healthcheck**: `/health`, timeout 120s
- **Generate domain**: assigns a public URL. Note it — the web service points at this.

### 3. Create the worker service

Right-click the API service → **Duplicate**. Then:

- Change **Variables**: `RUN_MODE=worker`
- Remove the public domain (worker has no inbound traffic)
- Healthcheck: turn OFF (no HTTP listener)

### 4. Run the one-shot migrate (first deploy only)

You can do this two ways:

**Option A — Railway CLI (recommended):**
```bash
railway run --service api python -m scripts.bootstrap_db --wait
```

**Option B — Temporary service:**
Duplicate the API service one more time, set `RUN_MODE=migrate`, deploy
once. It applies `src/db/schema.sql` (idempotent) then exits. Delete the
service after.

The schema is `CREATE TABLE IF NOT EXISTS` throughout, so it's safe to
re-run on every boot. The `entrypoint.sh` dispatcher does exactly that for
the `migrate` mode.

### 5. Create the web service

- **New → GitHub Repo** (this repo)
- Service settings → **Build → Dockerfile** → set to `web/Dockerfile`
- **Root directory**: `web`
- **Variables**:
  - `BACKEND_URL` — internal URL of the API service
    (`http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000` on Railway, or the
    public URL during initial smoke tests)
  - `PORT` — Railway injects automatically
- **Healthcheck**: `/`, timeout 120s
- **Generate domain**: this is your dashboard URL.

---

## Common Railway gotchas (and what this repo does about them)

| Problem | What we ship |
|---|---|
| Build fails because pyproject.toml not read | `requirements.txt` mirrors `pyproject.toml` deps as Nixpacks fallback |
| `pip install -e .` chokes on missing build backend | Dockerfile installs `setuptools wheel` before invoking `-e .`, falls back to `pip install -r requirements.txt` |
| App listens on 8000, Railway sends to `$PORT` | `entrypoint.sh` exports `$PORT` (defaulting to 8000 locally) and passes to uvicorn |
| Service crashloops on cold start before DB is ready | `entrypoint.sh` waits up to `DB_WAIT_SECS` (120) for Postgres before starting api/worker; lazy init then retries forever |
| Schema not applied → table-does-not-exist errors | One-shot `RUN_MODE=migrate` service applies schema; safe to re-run |
| Worker process eats SIGTERM and Railway force-kills | `tini` is the container init — reaps zombies and forwards SIGTERM cleanly |
| Worker has no `/health` so Railway thinks it's unhealthy | Worker service should have healthcheck **disabled** (settings UI) — only API + web have HTTP listeners |
| Same Dockerfile both services share — accidental drift | Single image, role selected by `RUN_MODE`. No drift possible. |
| CORS blocks the dashboard | API ships with `allow_origins=["*"]` for V1 |
| Environment shifts (`postgresql+asyncpg://` vs `postgresql://`) | `_normalize_url` accepts both forms |
| Web build can't find `package-lock.json` | `web/Dockerfile` does `npm ci || npm install` so either works |
| Static `public/` directory might not exist in builder | `web/Dockerfile` does `mkdir -p /app/public` before COPY |
| Lockfile + Next version drift causes CVE warnings | Pinned to Next 14.2.35; lockfile committed |

---

## Local smoke test before pushing to Railway

```bash
# Backend
docker build -t mptl-backend .
docker run --rm -e DATABASE_URL=postgresql://localhost:5432/test \
                -e RUN_MODE=api -p 8000:8000 mptl-backend
curl http://localhost:8000/health    # → {"status":"ok"}

# Web (after backend is up)
cd web && docker build -t mptl-web .
docker run --rm -e BACKEND_URL=http://host.docker.internal:8000 \
                -p 3000:3000 mptl-web
open http://localhost:3000
```

Or skip Docker entirely:
```bash
pip install -e .
python -m scripts.bootstrap_db --wait    # one-shot, applies schema
RUN_MODE=api python -m uvicorn src.api.main:app --port 8000   &
RUN_MODE=worker python -m src.runner.main &
cd web && npm install && npm run dev
```

---

## After-deploy sanity checklist

1. `GET /health` on api service → `{"status":"ok"}`
2. `GET /system/health` → DB status `"ok"`, `events_last_5min` rising
3. Web dashboard loads, sidebar visible, system-health widget shows green dots
4. Worker logs show `[polymarket_clob] subscribed to N assets` within 1 minute
5. After 5 minutes, `markets` table has rows: `select count(*) from markets;`
6. After 10 minutes, `market_events` table has rows: `select count(*) from market_events;`
7. (Optional) Click "Run replay" in Strategy Lab — completes within seconds
   if the time range is small

If any of those fail, check Railway logs for the affected service first.
The dispatcher prints `[entrypoint] starting mode=...` on every boot.
