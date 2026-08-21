"""SQLite schema and connection helpers for planz.db.

Ingest-owned tables are dropped and recreated on every ingest (idempotent).
Later phases (forecast, mps, scenario) own their tables and follow the same
pattern. Metric codes in `actuals`: 'ST' = Net Sell-Through, 'SI' = Sell-In
(Billings). `freight.geo` = 'ANY' means the mode is available to every geo.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

INGEST_SCHEMA = """
-- children first: actuals/prices reference series/calendar
DROP TABLE IF EXISTS actuals;
DROP TABLE IF EXISTS prices;

DROP TABLE IF EXISTS calendar;
CREATE TABLE calendar (
    week_label   TEXT PRIMARY KEY,
    fiscal_year  INTEGER NOT NULL,
    fiscal_week  INTEGER NOT NULL,
    fiscal_qtr   INTEGER NOT NULL,
    week_in_qtr  INTEGER NOT NULL,
    quarter_label TEXT NOT NULL,
    week_index   INTEGER NOT NULL UNIQUE,
    approx_monday TEXT NOT NULL,          -- ISO date, display only
    is_actual    INTEGER NOT NULL,        -- 1 if <= last actual week
    is_horizon   INTEGER NOT NULL         -- 1 if in forecast horizon
);

DROP TABLE IF EXISTS series;
CREATE TABLE series (
    series_id INTEGER PRIMARY KEY,
    channel   TEXT NOT NULL,
    geo       TEXT NOT NULL,
    customer  TEXT NOT NULL,
    ppn       INTEGER NOT NULL,
    variant   TEXT NOT NULL,
    sku       TEXT NOT NULL,
    -- sku is part of the key: 4 Ch3/G2 series exist twice, once under the
    -- regular G2_000x sku and once under a tiny 'Region 2_' bucket (docs D20)
    UNIQUE (channel, geo, customer, variant, sku)
);

CREATE TABLE actuals (
    series_id  INTEGER NOT NULL REFERENCES series(series_id),
    week_label TEXT NOT NULL REFERENCES calendar(week_label),
    metric     TEXT NOT NULL CHECK (metric IN ('ST', 'SI')),
    units      REAL NOT NULL,             -- negatives = returns, preserved
    PRIMARY KEY (series_id, week_label, metric)
);

CREATE TABLE prices (
    retailer   TEXT NOT NULL,
    variant    TEXT NOT NULL,
    week_label TEXT NOT NULL REFERENCES calendar(week_label),
    price      REAL NOT NULL,
    is_filled  INTEGER NOT NULL,          -- 0 = observed, 1 = peer-filled
                                          -- (Objective rule), 2 = own last
                                          -- price carried forward (no peer)
    PRIMARY KEY (retailer, variant, week_label)
);

DROP TABLE IF EXISTS seasonality;
CREATE TABLE seasonality (
    event       TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    week_label  TEXT NOT NULL,            -- may precede/exceed calendar range
    qtr_week    TEXT NOT NULL,            -- e.g. '2023_Q1_09' as given
    is_consistent INTEGER NOT NULL,       -- 0 = sheet's qtr_week contradicts
                                          -- the fiscal calendar (docs D22)
    PRIMARY KEY (event, fiscal_year)
);

DROP TABLE IF EXISTS variants;
CREATE TABLE variants (
    variant        TEXT PRIMARY KEY,
    part_number    INTEGER NOT NULL,
    classification TEXT NOT NULL CHECK (classification IN
        ('core', 'one_time_deal', 'exclusive', 'one_time_drop')),
    exclusive_retailer TEXT,              -- e.g. 'Retailer R3'
    release_week   TEXT,                  -- NULL = not stated in the sheet,
                                          -- NOT proof of pre-history launch
                                          -- (V5-V7 first sell 2022W43) so
                                          -- derive selling windows from
                                          -- actuals, not from this column
    eol_week       TEXT,                  -- e.g. V12 sold out week
    cap_g1         REAL,                  -- exclusive lifetime volume by geo
    cap_g2         REAL,
    cap_g35        REAL,
    cap_total      REAL                   -- one-time-deal / drop lifetime cap
);

DROP TABLE IF EXISTS params;
CREATE TABLE params (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

DROP TABLE IF EXISTS freight;
CREATE TABLE freight (
    mode            TEXT NOT NULL,
    geo             TEXT NOT NULL,        -- 'ANY' = all geos
    lead_time_weeks INTEGER NOT NULL,
    cost_per_unit   REAL NOT NULL,
    PRIMARY KEY (mode, geo)
);

CREATE INDEX IF NOT EXISTS idx_actuals_week ON actuals(week_label);
"""

# Owned by the forecast stage (phase 2); rebuilt on every --forecast run.
# No FKs into ingest tables (see init_ingest_schema note).
FORECAST_SCHEMA = """
DROP TABLE IF EXISTS forecast;
CREATE TABLE forecast (
    variant    TEXT NOT NULL,
    geo        TEXT NOT NULL,
    channel    TEXT NOT NULL,
    week_label TEXT NOT NULL,
    p10        REAL NOT NULL,
    p50        REAL NOT NULL,
    p90        REAL NOT NULL,
    method     TEXT NOT NULL CHECK (method IN ('xgb', 'npi_ramp', 'eol_zero')),
    PRIMARY KEY (variant, geo, channel, week_label)
);

DROP TABLE IF EXISTS forecast_scores;
CREATE TABLE forecast_scores (
    model      TEXT NOT NULL,             -- 'xgb' | 'naive' | 'seasonal_naive'
    scope_type TEXT NOT NULL,             -- 'overall' | 'geo' | 'variant'
    scope      TEXT NOT NULL,
    wape       REAL NOT NULL,
    smape      REAL NOT NULL,
    bias       REAL NOT NULL,
    pinball10  REAL,                      -- xgb only
    pinball90  REAL,
    PRIMARY KEY (model, scope_type, scope)
);
"""

# Owned by the MPS/scenario stages (phases 3-4); plan_id 'baseline'|'scenario'.
# CREATE IF NOT EXISTS (no drops): plans are plan_id-scoped, and re-running
# one stage must never destroy another stage's stored plan.
MPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS mps (
    plan_id    TEXT NOT NULL,
    variant    TEXT NOT NULL,
    week_label TEXT NOT NULL,
    production REAL NOT NULL,
    packout    INTEGER NOT NULL,          -- 1 if the variant uses a slot
    PRIMARY KEY (plan_id, variant, week_label)
);

CREATE TABLE IF NOT EXISTS shipments (
    plan_id    TEXT NOT NULL,
    variant    TEXT NOT NULL,
    geo        TEXT NOT NULL,
    week_label TEXT NOT NULL,             -- ship week (OEM side)
    mode       TEXT NOT NULL,
    units      REAL NOT NULL,
    cost       REAL NOT NULL,
    PRIMARY KEY (plan_id, variant, geo, week_label, mode)
);

CREATE TABLE IF NOT EXISTS inventory (
    plan_id     TEXT NOT NULL,
    variant     TEXT NOT NULL,
    geo         TEXT NOT NULL,
    week_label  TEXT NOT NULL,
    on_hand     REAL NOT NULL,            -- at destination DC, end of week
    in_transit  REAL NOT NULL,
    ch3_inventory REAL NOT NULL,          -- reseller channel stock
    wos_supply  REAL,                     -- run-out WOS of on_hand+in_transit
    wos_channel REAL,                     -- run-out WOS of ch3 stock vs Ch3 demand
    short_direct REAL NOT NULL,           -- unmet Ch1+Ch2 demand this week
    short_ch3   REAL NOT NULL,            -- unmet Ch3 sell-through this week
    PRIMARY KEY (plan_id, variant, geo, week_label)
);

CREATE TABLE IF NOT EXISTS validation (
    plan_id    TEXT NOT NULL,
    check_name TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL')),
    detail     TEXT NOT NULL,
    PRIMARY KEY (plan_id, check_name)
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    # isolation_level=None: no implicit transactions — callers that write
    # (ingest) manage BEGIN/COMMIT/ROLLBACK explicitly so schema rebuild and
    # inserts commit atomically. Readers are unaffected.
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _run_script(conn: sqlite3.Connection, script: str) -> None:
    # NOTE: naive split — schema comments must never contain ';'.
    for stmt in script.split(";"):
        if stmt.strip():
            conn.execute(stmt)


def init_forecast_schema(conn: sqlite3.Connection) -> None:
    _run_script(conn, FORECAST_SCHEMA)


def init_mps_schema(conn: sqlite3.Connection) -> None:
    _run_script(conn, MPS_SCHEMA)


def init_ingest_schema(conn: sqlite3.Connection) -> None:
    # Statement-by-statement (not executescript, which force-commits) so the
    # DDL joins the caller's open transaction. Later-phase tables (forecast,
    # mps, scenario) must NOT declare FKs into these tables: ingest rebuilds
    # them wholesale, and series_id is not stable across ingests.
    _run_script(conn, INGEST_SCHEMA)
