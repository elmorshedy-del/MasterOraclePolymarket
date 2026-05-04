-- Master Paper Trade Lab — Postgres schema
-- See DESIGN.md for the conceptual model.
--
-- Conventions:
--   - All timestamps are TIMESTAMPTZ (UTC).
--   - Money is NUMERIC(18, 6).
--   - Sizes (token counts) are NUMERIC(18, 6).
--   - Prices on Polymarket are 0.0–1.0; we store NUMERIC(8, 6).
--   - High-volume tables are partitioned by day where noted.
--   - Denormalized analytics tags live on paper_trades for fast pivots.

-- ---------------------------------------------------------------------------
-- Markets and metadata
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS markets (
    market_id          TEXT PRIMARY KEY,
    venue              TEXT NOT NULL,
    venue_market_id    TEXT NOT NULL,
    title              TEXT NOT NULL,
    category           TEXT NOT NULL,
    subcategory        TEXT,
    end_time           TIMESTAMPTZ,
    tick_size          NUMERIC(8, 6),
    asset_ids          TEXT[] NOT NULL,
    tags_extra         JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at        TIMESTAMPTZ,
    resolution         JSONB,
    UNIQUE (venue, venue_market_id)
);

CREATE INDEX IF NOT EXISTS idx_markets_category ON markets (category);
CREATE INDEX IF NOT EXISTS idx_markets_end_time ON markets (end_time) WHERE end_time IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Event log — the foundation for replay (Tier 2 fidelity)
-- ---------------------------------------------------------------------------
-- V1 ships UNPARTITIONED — the retention sweeper handles cleanup via DELETE,
-- which is sufficient at the $50/mo Railway scale we target. The previous
-- ``PARTITION BY RANGE (ts)`` declaration referenced a partition manager
-- that was never written; with no child partition every INSERT failed,
-- which broke ingestion entirely. If the table grows past ~5 GB we revisit
-- partitioning with a working bucket-creation job.

CREATE TABLE IF NOT EXISTS market_events (
    id              BIGSERIAL PRIMARY KEY,
    event_id        UUID NOT NULL,
    event_type      TEXT NOT NULL,
    market_id       TEXT,
    asset_id        TEXT,
    venue           TEXT NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    payload         JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_market_ts ON market_events (market_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_type_ts   ON market_events (event_type, ts);

-- Aggregated views for storage retention
CREATE TABLE IF NOT EXISTS market_bars_1m (
    market_id     TEXT NOT NULL,
    asset_id      TEXT NOT NULL,
    bucket_ts     TIMESTAMPTZ NOT NULL,
    open_price    NUMERIC(8, 6),
    high_price    NUMERIC(8, 6),
    low_price     NUMERIC(8, 6),
    close_price   NUMERIC(8, 6),
    volume        NUMERIC(18, 6),
    trade_count   INTEGER,
    bid_at_close  NUMERIC(8, 6),
    ask_at_close  NUMERIC(8, 6),
    PRIMARY KEY (market_id, asset_id, bucket_ts)
);

CREATE TABLE IF NOT EXISTS market_bars_1d (
    market_id     TEXT NOT NULL,
    asset_id      TEXT NOT NULL,
    bucket_ts     DATE NOT NULL,
    open_price    NUMERIC(8, 6),
    high_price    NUMERIC(8, 6),
    low_price     NUMERIC(8, 6),
    close_price   NUMERIC(8, 6),
    volume        NUMERIC(18, 6),
    trade_count   INTEGER,
    PRIMARY KEY (market_id, asset_id, bucket_ts)
);

-- ---------------------------------------------------------------------------
-- Sleeves
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sleeves (
    sleeve_id            TEXT PRIMARY KEY,
    strategy_name        TEXT NOT NULL,
    config_id            TEXT NOT NULL,
    edge_class           TEXT,
    starting_capital_usd NUMERIC(18, 6) NOT NULL,
    mode                 TEXT NOT NULL,
    enabled              BOOLEAN NOT NULL DEFAULT TRUE,
    config_hash          TEXT NOT NULL,
    started_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_mode_change_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sleeve_mode_history (
    id                BIGSERIAL PRIMARY KEY,
    sleeve_id         TEXT NOT NULL REFERENCES sleeves(sleeve_id),
    from_mode         TEXT,
    to_mode           TEXT NOT NULL,
    config_hash       TEXT NOT NULL,
    changed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason            TEXT
);

CREATE INDEX IF NOT EXISTS idx_sleeve_mode_history_sleeve ON sleeve_mode_history (sleeve_id, changed_at);

-- ---------------------------------------------------------------------------
-- Signals — strategy outputs, regardless of mode
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS signals (
    signal_id        UUID PRIMARY KEY,
    sleeve_id        TEXT NOT NULL REFERENCES sleeves(sleeve_id),
    strategy_name    TEXT NOT NULL,
    config_id        TEXT NOT NULL,
    market_id        TEXT NOT NULL,
    asset_id         TEXT NOT NULL,
    side             TEXT NOT NULL,
    order_type       TEXT NOT NULL,
    price            NUMERIC(8, 6),
    size             NUMERIC(18, 6) NOT NULL,
    reason           TEXT NOT NULL,
    ts_signal        TIMESTAMPTZ NOT NULL,
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_signals_sleeve_ts ON signals (sleeve_id, ts_signal);

-- ---------------------------------------------------------------------------
-- Paper orders / fills / trades
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS paper_orders (
    order_id      UUID PRIMARY KEY,
    signal_id     UUID NOT NULL REFERENCES signals(signal_id),
    sleeve_id     TEXT NOT NULL REFERENCES sleeves(sleeve_id),
    market_id     TEXT NOT NULL,
    asset_id      TEXT NOT NULL,
    side          TEXT NOT NULL,
    order_type    TEXT NOT NULL,
    price         NUMERIC(8, 6),
    size          NUMERIC(18, 6) NOT NULL,
    ts_signal     TIMESTAMPTZ NOT NULL,
    ts_placed     TIMESTAMPTZ NOT NULL,
    status        TEXT NOT NULL DEFAULT 'open',  -- open | partially_filled | filled | cancelled
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_paper_orders_sleeve_status ON paper_orders (sleeve_id, status);

CREATE TABLE IF NOT EXISTS paper_fills (
    fill_id       UUID PRIMARY KEY,
    order_id      UUID NOT NULL REFERENCES paper_orders(order_id),
    sleeve_id     TEXT NOT NULL REFERENCES sleeves(sleeve_id),
    market_id     TEXT NOT NULL,
    asset_id      TEXT NOT NULL,
    side          TEXT NOT NULL,
    price         NUMERIC(8, 6) NOT NULL,
    size          NUMERIC(18, 6) NOT NULL,
    fill_type     TEXT NOT NULL,
    ts_filled     TIMESTAMPTZ NOT NULL,
    realism_flag  TEXT NOT NULL DEFAULT 'clean',
    gas_cost_usd  NUMERIC(18, 6) NOT NULL DEFAULT 0.10,
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_paper_fills_sleeve_ts ON paper_fills (sleeve_id, ts_filled);

CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id              UUID PRIMARY KEY,
    sleeve_id             TEXT NOT NULL REFERENCES sleeves(sleeve_id),
    strategy_name         TEXT NOT NULL,
    config_id             TEXT NOT NULL,
    config_hash           TEXT NOT NULL,
    market_id             TEXT NOT NULL,
    asset_id              TEXT NOT NULL,
    side                  TEXT NOT NULL,
    entry_price           NUMERIC(8, 6) NOT NULL,
    entry_size            NUMERIC(18, 6) NOT NULL,
    entry_ts              TIMESTAMPTZ NOT NULL,
    exit_price            NUMERIC(8, 6),
    exit_size             NUMERIC(18, 6),
    exit_ts               TIMESTAMPTZ,
    pnl_usd               NUMERIC(18, 6),
    pnl_after_haircut_usd NUMERIC(18, 6),
    realism_flag          TEXT NOT NULL DEFAULT 'clean',
    fill_type             TEXT NOT NULL,
    -- denormalized analytics tags (one column per dimension for fast pivot)
    market_category            TEXT,
    market_subcategory         TEXT,
    liquidity_bucket           TEXT,
    entry_price_bucket         TEXT,
    time_to_resolution_bucket  TEXT,
    orderbook_state_bucket     TEXT,
    time_of_day_bucket         TEXT,
    day_of_week                INT,
    news_regime                TEXT,
    counterparty_estimate      TEXT,
    -- open extension for new tag plugins without schema migration
    tags_extra            JSONB NOT NULL DEFAULT '{}'::jsonb,
    source                TEXT NOT NULL DEFAULT 'live'  -- 'live' | 'replay'
);

CREATE INDEX IF NOT EXISTS idx_paper_trades_sleeve_ts ON paper_trades (sleeve_id, entry_ts);
CREATE INDEX IF NOT EXISTS idx_paper_trades_category  ON paper_trades (market_category);
CREATE INDEX IF NOT EXISTS idx_paper_trades_strategy  ON paper_trades (strategy_name);
CREATE INDEX IF NOT EXISTS idx_paper_trades_source    ON paper_trades (source);

-- ---------------------------------------------------------------------------
-- Positions
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS paper_positions (
    sleeve_id     TEXT NOT NULL REFERENCES sleeves(sleeve_id),
    market_id     TEXT NOT NULL,
    asset_id      TEXT NOT NULL,
    side          TEXT NOT NULL,
    size          NUMERIC(18, 6) NOT NULL,
    avg_entry     NUMERIC(8, 6) NOT NULL,
    opened_at     TIMESTAMPTZ NOT NULL,
    last_updated  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sleeve_id, market_id, asset_id, side)
);

-- ---------------------------------------------------------------------------
-- P&L snapshots (for equity curves)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sleeve_pnl_snapshots (
    sleeve_id           TEXT NOT NULL REFERENCES sleeves(sleeve_id),
    ts                  TIMESTAMPTZ NOT NULL,
    realized_pnl_usd    NUMERIC(18, 6) NOT NULL,
    unrealized_pnl_usd  NUMERIC(18, 6) NOT NULL,
    capital_remaining   NUMERIC(18, 6) NOT NULL,
    open_positions      INT NOT NULL,
    PRIMARY KEY (sleeve_id, ts)
);

-- ---------------------------------------------------------------------------
-- Replay runs (Strategy Lab)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS replay_runs (
    run_id          UUID PRIMARY KEY,
    sleeve_id       TEXT,                    -- nullable: replay can target a strategy without a sleeve
    strategy_name   TEXT NOT NULL,
    config_id       TEXT NOT NULL,
    config_hash     TEXT NOT NULL,
    overrides       JSONB NOT NULL DEFAULT '{}'::jsonb,
    range_start     TIMESTAMPTZ NOT NULL,
    range_end       TIMESTAMPTZ NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running',
    summary         JSONB                    -- key metrics for quick display
);

CREATE INDEX IF NOT EXISTS idx_replay_runs_strategy ON replay_runs (strategy_name, started_at);

-- ---------------------------------------------------------------------------
-- Tier 3 calibration (off by default)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS calibration_trips (
    id                          BIGSERIAL PRIMARY KEY,
    paper_fill_id               UUID NOT NULL REFERENCES paper_fills(fill_id),
    real_order_tx_hash          TEXT,
    real_fill_price             NUMERIC(8, 6),
    real_fill_ts                TIMESTAMPTZ,
    paper_predicted_fill_price  NUMERIC(8, 6) NOT NULL,
    paper_predicted_fill_ts     TIMESTAMPTZ NOT NULL,
    delta_price                 NUMERIC(8, 6),
    delta_ts_ms                 BIGINT,
    notes                       TEXT
);
