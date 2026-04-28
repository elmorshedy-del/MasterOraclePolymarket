"""FastAPI surface for the dashboard.

Phase 0: health check only. Phase 3 fleshes out the full read API
(sleeves, equity curves, trades, pivots, replay triggers).
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Master Paper Trade Lab API", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
async def version() -> dict[str, str]:
    return {"version": "0.1.0", "phase": "0"}
