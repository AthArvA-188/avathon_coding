"""Ingest program_z.xlsx into planz.db (idempotent; the xlsx is never written).

Reads the five sheets, normalizes them into the schema in db.py, and returns
per-table row counts. Negative actuals (returns) are preserved as-is; the
forecast layer decides how to treat them (docs/decisions.md D8).

The whole ingest — schema rebuild plus inserts — runs in ONE transaction, and
all sheets are parsed before the database is touched, so a failed ingest
leaves the previous database intact.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

from . import calendar as cal
from . import db, params

WEEK_COL_RE = re.compile(r"^\d{4}W\d{2}$")
QTR_WK_RE = re.compile(r"^(\d{4})_Q(\d)_(\d{2})$")
METRIC_CODES = {"Net Sell-Through": "ST", "Sell-In (Billings)": "SI"}


def _week_from_yearweek(yw: int) -> str:
    """Pricing YEAR_WEEK int (e.g. 202143) -> label '2021W43'."""
    return cal.week_label(yw // 100, yw % 100)


def ingest_calendar(conn: sqlite3.Connection, week_cols: list[str]) -> int:
    horizon = set(cal.week_range(params.HORIZON_START, params.HORIZON_END))
    last_idx = cal.week_index(params.LAST_ACTUAL_WEEK)
    rows = []
    for label in week_cols:
        year, week = cal.parse_week(label)
        qtr, wiq = cal.fiscal_qtr_week(label)
        rows.append((
            label, year, week, qtr, wiq, cal.quarter_label(label),
            cal.week_index(label), cal.approx_monday(label).isoformat(),
            int(cal.week_index(label) <= last_idx), int(label in horizon),
        ))
    conn.executemany("INSERT INTO calendar VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def ingest_series_actuals(conn: sqlite3.Connection, data: pd.DataFrame,
                          week_cols: list[str]) -> tuple[int, int]:
    id_cols = {
        "channel": "Channel Level 2 Desc.",
        "geo": "Geo Level 1 Desc.",
        "customer": "Customer Sold To Desc.",
        "ppn": "PPN",
        "variant": "Variant Desc.",
        "sku": "SKU",
    }
    d = data.rename(columns={v: k for k, v in id_cols.items()}).copy()
    # Data quirk (docs D20): 4 Channel 3 / Geo G2 series carry SKU 'Region 2_'
    # with a blank PPN — fill PPN from the variant number, keep them separate.
    missing = d["ppn"].isna()
    d.loc[missing, "ppn"] = (d.loc[missing, "variant"]
                             .str.extract(r"V(\d+)$", expand=False).astype(float))
    if d["ppn"].isna().any():
        raise ValueError("PPN missing and not derivable from variant name")
    d["ppn"] = d["ppn"].astype(int)
    d["metric"] = d["Values"].map(METRIC_CODES)
    if d["metric"].isna().any():
        bad = d.loc[d["metric"].isna(), "Values"].unique()
        raise ValueError(f"unknown metric labels: {bad}")

    keys = list(id_cols)
    series = (d[keys].drop_duplicates()
              .sort_values(["channel", "geo", "customer", "ppn", "sku"])
              .reset_index(drop=True))
    series.insert(0, "series_id", series.index + 1)
    conn.executemany(
        "INSERT INTO series VALUES (?,?,?,?,?,?,?)",
        series.itertuples(index=False, name=None),
    )

    actual_weeks = [w for w in week_cols
                    if cal.week_index(w) <= cal.week_index(params.LAST_ACTUAL_WEEK)]
    merged = d.merge(series, on=keys, validate="many_to_one")
    long = merged.melt(
        id_vars=["series_id", "metric"], value_vars=actual_weeks,
        var_name="week_label", value_name="units",
    )
    if long["units"].isna().any():
        n = int(long["units"].isna().sum())
        raise ValueError(f"{n} blank cells inside the actuals window")
    # raise loudly on text cells ('1,234', '5 (est)') that SQLite would
    # otherwise store as TEXT and silently mis-sum later
    long["units"] = pd.to_numeric(long["units"], errors="raise")
    conn.executemany(
        "INSERT INTO actuals (series_id, week_label, metric, units) VALUES (?,?,?,?)",
        long[["series_id", "week_label", "metric", "units"]]
            .itertuples(index=False, name=None),
    )
    return len(series), len(long)


def ingest_prices(conn: sqlite3.Connection, pricing: pd.DataFrame) -> tuple[int, int]:
    # Data quirk (docs D21): 168 daily rows (Retailer R2, V1-V4) carry a
    # price of exactly 0 — placeholder zeros, not real prices. Drop them so
    # the peer-fill rule supplies those retailer-weeks instead.
    p = pricing[pricing["Price"] > 0].copy()
    p["week_label"] = p["YEAR_WEEK"].astype(int).map(_week_from_yearweek)

    # Average per DAY first: the extract duplicates 2022-02-28 for 15
    # retailer-variant pairs, and a row-level mean would double-weight it.
    daily = (p.groupby(["Retailer", "Variant", "Date", "week_label"],
                       as_index=False)["Price"].mean())
    weekly = (daily.groupby(["Retailer", "Variant", "week_label"],
                            as_index=False)["Price"].mean())
    weekly["week_idx"] = weekly["week_label"].map(cal.week_index)

    # Peer-fill (Objective rule): a top retailer missing a price in a week
    # takes the mean of the peers that do have one. Fill is bounded to each
    # retailer-variant pair's own observed carry window [first, last] so we
    # never invent pre-launch or post-exit prices, and never create rows for
    # retailers that never carried the variant (e.g. V5-V7 are R4-only).
    peer = (weekly.groupby(["Variant", "week_label"])["Price"]
            .mean().rename("peer_price"))
    frames = []
    for (retailer, variant), g in weekly.groupby(["Retailer", "Variant"]):
        lo, hi = int(g["week_idx"].min()), int(g["week_idx"].max())
        frames.append(pd.DataFrame({
            "Retailer": retailer, "Variant": variant, "week_idx": range(lo, hi + 1),
            "week_label": [cal.from_index(i) for i in range(lo, hi + 1)],
        }))
    grid = pd.concat(frames, ignore_index=True)
    full = grid.merge(weekly[["Retailer", "Variant", "week_label", "Price"]],
                      on=["Retailer", "Variant", "week_label"], how="left")
    full = full.join(peer, on=["Variant", "week_label"])
    # is_filled: 0 = observed, 1 = peer mean, 2 = own last price carried
    # forward (sole-carrier variants like V5-V7/R4 have gap weeks with no
    # same-week peer to borrow from).
    observed = full["Price"].notna()
    has_peer = full["peer_price"].notna()
    full["is_filled"] = 2 - observed.astype(int) * 2 - ((~observed) & has_peer).astype(int)
    full["Price"] = full["Price"].fillna(full["peer_price"])
    full = full.sort_values(["Retailer", "Variant", "week_idx"])
    full["Price"] = full.groupby(["Retailer", "Variant"])["Price"].ffill()
    if full["Price"].isna().any():
        gaps = full[full["Price"].isna()]
        raise ValueError(f"{len(gaps)} unfillable price gaps: "
                         f"{gaps[['Retailer', 'Variant', 'week_label']].values[:5]}")

    conn.executemany(
        "INSERT INTO prices (retailer, variant, week_label, price, is_filled) "
        "VALUES (?,?,?,?,?)",
        full[["Retailer", "Variant", "week_label", "Price", "is_filled"]]
            .itertuples(index=False, name=None),
    )
    return len(full), int((full["is_filled"] > 0).sum())


def ingest_seasonality(conn: sqlite3.Connection, raw: pd.DataFrame) -> int:
    rows = []
    for col in range(1, raw.shape[1], 2):
        year = int(raw.iat[0, col])
        for r in range(2, raw.shape[0]):
            event = raw.iat[r, 0]
            if pd.isna(event):
                continue
            qtr_cell, cy_cell = raw.iat[r, col], raw.iat[r, col + 1]
            if pd.isna(qtr_cell) or pd.isna(cy_cell):
                raise ValueError(f"blank seasonality cell: {event!r} {year}")
            qtr_week = str(qtr_cell).strip()          # '2023_Q1_09'
            cy, wk = str(cy_cell).strip().split("_")  # '2023_09'
            label = cal.week_label(int(cy), int(wk))
            # is_consistent: does the sheet's own quarter-week agree with the
            # fiscal calendar? The two fiscal-2024 Promo Q4 rows do not
            # (docs D22) and must be distinguishable downstream.
            m = QTR_WK_RE.match(qtr_week)
            consistent = int(bool(m) and
                             cal.fiscal_qtr_week(label) == (int(m.group(2)),
                                                            int(m.group(3))))
            rows.append((str(event).strip(), year, label, qtr_week, consistent))
    conn.executemany("INSERT INTO seasonality VALUES (?,?,?,?,?)", rows)
    return len(rows)


def _parse_variant_row(row: pd.Series) -> dict:
    cls_raw = str(row["Core/Exclusive"]).strip()
    notes = "" if pd.isna(row.get("Notes")) else str(row["Notes"])
    out = {
        "variant": str(row["Variant"]).strip(),
        "part_number": int(row["Part Number"]),
        "exclusive_retailer": None, "release_week": None, "eol_week": None,
        "cap_g1": None, "cap_g2": None, "cap_g35": None, "cap_total": None,
    }
    retailer_m = re.search(r"Retailer (R\d)", cls_raw)
    release_m = re.search(r"Released (\d{4}W\d{2})", notes)
    soldout_m = re.search(r"Sold out (\d{4}W\d{2})", cls_raw)
    otd_cap_m = re.search(r"(\d+)k lifetime volume", cls_raw)

    if cls_raw == "Core":
        out["classification"] = "core"
    elif cls_raw.startswith("One Time Deal"):
        out["classification"] = "one_time_deal"
        out["exclusive_retailer"] = f"Retailer {retailer_m.group(1)}"
        out["cap_total"] = int(otd_cap_m.group(1)) * 1000
    elif "Exclusive" in cls_raw:
        out["classification"] = "exclusive"
        out["exclusive_retailer"] = f"Retailer {retailer_m.group(1)}"
        out["cap_g1"] = float(row["Geo G1"])
        out["cap_g2"] = float(row["Geo G2"])
        out["cap_g35"] = float(row["Geo G3-5"])
        out["cap_total"] = out["cap_g1"] + out["cap_g2"] + out["cap_g35"]
    elif cls_raw.startswith("One time drop"):
        out["classification"] = "one_time_drop"
        # 'less than 1k lifetime volume' -> conservative 1,000 cap
        out["cap_total"] = 1000
        out["eol_week"] = soldout_m.group(1) if soldout_m else None
    else:
        raise ValueError(f"unrecognized classification: {cls_raw!r}")

    out["release_week"] = release_m.group(1) if release_m else None
    return out


def ingest_variants(conn: sqlite3.Connection, details: pd.DataFrame) -> int:
    rows = [_parse_variant_row(r) for _, r in details.iterrows()
            if pd.notna(r["Variant"])]
    conn.executemany(
        "INSERT INTO variants (variant, part_number, classification,"
        " exclusive_retailer, release_week, eol_week, cap_g1, cap_g2, cap_g35,"
        " cap_total) VALUES (:variant, :part_number, :classification,"
        " :exclusive_retailer, :release_week, :eol_week, :cap_g1, :cap_g2,"
        " :cap_g35, :cap_total)",
        rows,
    )
    return len(rows)


def ingest_params(conn: sqlite3.Connection) -> int:
    conn.executemany("INSERT INTO params VALUES (?,?)", params.as_param_rows())
    conn.executemany("INSERT INTO freight VALUES (?,?,?,?)",
                     params.FREIGHT_OPTIONS)
    return len(params.FREIGHT_OPTIONS)


def run(xlsx_path: str | Path, db_path: str | Path) -> dict[str, int]:
    # Parse everything BEFORE touching the DB: a malformed sheet must never
    # leave a half-wiped database behind.
    with pd.ExcelFile(xlsx_path) as xl:
        data = xl.parse("Data - 104 weeks", header=0)
        pricing = xl.parse("Pricing Data", header=0)
        seasonality_raw = xl.parse("Strong Seasonality Weeks", header=None)
        details = xl.parse("Variant Details", header=0)
    week_cols = [c for c in data.columns
                 if isinstance(c, str) and WEEK_COL_RE.match(c)]

    conn = db.connect(db_path)
    try:
        # One explicit transaction around schema rebuild AND inserts: any
        # failure rolls back to the previous good database state.
        conn.execute("BEGIN IMMEDIATE")
        try:
            db.init_ingest_schema(conn)
            counts = {"calendar": ingest_calendar(conn, week_cols)}
            counts["series"], counts["actuals"] = ingest_series_actuals(
                conn, data, week_cols)
            counts["prices"], counts["prices_filled"] = ingest_prices(
                conn, pricing)
            counts["seasonality"] = ingest_seasonality(conn, seasonality_raw)
            counts["variants"] = ingest_variants(conn, details)
            counts["freight"] = ingest_params(conn)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return counts
