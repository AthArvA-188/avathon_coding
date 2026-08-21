"""Ingest reconciliation: everything in SQLite must match an independent
recomputation from the raw xlsx (counts, totals at full series grain,
negatives, price fill values, caps, params double-entry, quirks)."""
from pathlib import Path

import pandas as pd
import pytest

from planz import ingest as planz_ingest

XLSX = Path(__file__).resolve().parents[2] / "program_z.xlsx"
RETAILERS = ["Retailer R1", "Retailer R2", "Retailer R3", "Retailer R4"]


@pytest.fixture(scope="module")
def raw_data(raw_xl):
    d = raw_xl.parse("Data - 104 weeks", header=0)
    weeks = [c for c in d.columns if isinstance(c, str) and len(c) == 7 and c[4] == "W"]
    filled = [c for c in weeks if d[c].notna().any()]
    return d, weeks, filled


@pytest.fixture(scope="module")
def weekly_prices(raw_xl):
    """Independent recomputation of weekly prices: drop zero placeholders,
    average per day first (duplicate extract rows), then average days into
    weeks. Returns {(retailer, variant, week_label): price}."""
    p = raw_xl.parse("Pricing Data", header=0)
    pos = p[p["Price"] > 0].copy()
    pos["week_label"] = pos["YEAR_WEEK"].astype(int).map(
        lambda yw: f"{yw // 100}W{yw % 100:02d}")
    day = pos.groupby(["Retailer", "Variant", "Date", "week_label"],
                      as_index=False)["Price"].mean()
    wk = day.groupby(["Retailer", "Variant", "week_label"],
                     as_index=False)["Price"].mean()
    return {(r, v, w): x for r, v, w, x in
            wk.itertuples(index=False, name=None)}


def q1(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


def test_row_counts(counts, conn):
    assert counts["calendar"] == 156
    assert counts["series"] == 154
    assert counts["actuals"] == 154 * 104 * 2 == 32_032
    assert counts["prices"] == 2_199
    assert counts["prices_filled"] == 127
    assert counts["seasonality"] == 52
    assert counts["variants"] == 12
    assert q1(conn, "SELECT COUNT(*) FROM actuals") == 32_032
    assert q1(conn, "SELECT COUNT(*) FROM prices") == 2_199
    assert q1(conn, "SELECT COUNT(*) FROM prices WHERE is_filled > 0") == 127


def test_ingest_idempotent(tmp_path):
    import sqlite3

    def snapshot(db_path):
        conn = sqlite3.connect(db_path)
        try:
            return (conn.execute("SELECT COUNT(*), SUM(units) FROM actuals").fetchone(),
                    conn.execute("SELECT COUNT(*), SUM(price) FROM prices").fetchone(),
                    conn.execute("SELECT COUNT(*) FROM series").fetchone())
        finally:
            conn.close()

    db_path = tmp_path / "planz_idem.db"
    c1 = planz_ingest.run(XLSX, db_path)
    snap1 = snapshot(db_path)
    c2 = planz_ingest.run(XLSX, db_path)
    assert c1 == c2
    assert snapshot(db_path) == snap1
    assert snap1[0][0] == 32_032


def test_calendar_flags(conn):
    assert q1(conn, "SELECT COUNT(*) FROM calendar WHERE is_actual = 1") == 104
    assert q1(conn, "SELECT COUNT(*) FROM calendar WHERE is_horizon = 1") == 52
    assert q1(conn, "SELECT COUNT(*) FROM calendar WHERE is_actual + is_horizon <> 1") == 0
    assert q1(conn, "SELECT MAX(week_label) FROM calendar WHERE is_actual = 1") == "2023W39"


def test_negatives_preserved(conn, raw_data):
    d, _, filled = raw_data
    raw_neg = int((d[filled].apply(pd.to_numeric, errors="coerce") < 0).sum().sum())
    assert raw_neg == 218
    assert q1(conn, "SELECT COUNT(*) FROM actuals WHERE units < 0") == raw_neg


def test_totals_match_raw_at_full_series_grain(conn, raw_data):
    d, _, filled = raw_data
    key_cols = ["Channel Level 2 Desc.", "Geo Level 1 Desc.",
                "Customer Sold To Desc.", "Variant Desc.", "SKU"]
    for metric_label, code in [("Net Sell-Through", "ST"),
                               ("Sell-In (Billings)", "SI")]:
        sub = d[d["Values"] == metric_label]
        assert len(sub) == 154              # guard against vacuous pass
        raw_tot = (sub[filled].sum(axis=1)
                   .groupby([sub[c] for c in key_cols]).sum())
        db_tot = {tuple(r)[:5]: r[5] for r in conn.execute(
            "SELECT s.channel, s.geo, s.customer, s.variant, s.sku,"
            " SUM(a.units) FROM actuals a JOIN series s USING (series_id)"
            " WHERE a.metric = ? GROUP BY 1,2,3,4,5", (code,))}
        assert len(db_tot) == 154
        for key, expected in raw_tot.items():
            assert db_tot[key] == pytest.approx(float(expected)), (key, code)


def test_npi_and_eol_variants_have_zero_history(conn):
    # guard: the series must exist before zero-sum assertions mean anything
    for v, n in [("Variant V10", 6), ("Variant V11", 5), ("Variant V12", 5)]:
        assert q1(conn, "SELECT COUNT(*) FROM series WHERE variant = ?", v) == n
    for v in ("Variant V10", "Variant V11"):
        assert q1(conn,
                  "SELECT COALESCE(SUM(ABS(a.units)), 0) FROM actuals a"
                  " JOIN series s ON s.series_id = a.series_id"
                  " WHERE s.variant = ?", v) == 0
    # V12 sold out 2022W14; one straggler unit at 2023W18 exists in the raw
    # data (kept as-is), so post-EOL activity must be negligible, not zero
    assert q1(conn,
              "SELECT COALESCE(SUM(ABS(a.units)), 0) FROM actuals a"
              " JOIN series s ON s.series_id = a.series_id"
              " WHERE s.variant = 'Variant V12' AND a.metric = 'ST'"
              " AND a.week_label > '2022W14'") <= 1
    assert 0 < q1(conn,
                  "SELECT SUM(a.units) FROM actuals a"
                  " JOIN series s ON s.series_id = a.series_id"
                  " WHERE s.variant = 'Variant V12' AND a.metric = 'ST'") <= 1000


def test_price_spans_contiguous_and_bounded(conn):
    pairs = conn.execute(
        "SELECT p.retailer, p.variant, COUNT(*) AS n, MIN(c.week_index) AS lo,"
        " MAX(c.week_index) AS hi, MIN(p.price) AS minp"
        " FROM prices p JOIN calendar c ON c.week_label = p.week_label"
        " GROUP BY 1, 2").fetchall()
    assert len(pairs) == 19                 # not the full 4x7 grid: no
    for r in pairs:                         # fabricated retailer-variant pairs
        assert r["n"] == r["hi"] - r["lo"] + 1, (r["retailer"], r["variant"])
        assert r["minp"] > 0
    # V5-V7 are One Time Deals carried by R4 alone
    assert conn.execute(
        "SELECT DISTINCT retailer FROM prices WHERE variant IN"
        " ('Variant V5','Variant V6','Variant V7')").fetchall()[0][0] == "Retailer R4"
    # spans honor reality: R4 prices from launch; R3 delists at 2023W47
    assert q1(conn, "SELECT MIN(week_label) FROM prices"
                    " WHERE retailer = 'Retailer R4'") == "2021W43"
    assert q1(conn, "SELECT MAX(week_label) FROM prices"
                    " WHERE retailer = 'Retailer R3'") == "2023W47"
    assert q1(conn, "SELECT MAX(week_label) FROM prices") == "2024W27"
    assert q1(conn, "SELECT COUNT(*) FROM prices"
                    " WHERE is_filled NOT IN (0, 1, 2)") == 0


def test_observed_prices_match_independent_recomputation(conn, weekly_prices):
    db_obs = conn.execute(
        "SELECT retailer, variant, week_label, price FROM prices"
        " WHERE is_filled = 0").fetchall()
    assert len(db_obs) == len(weekly_prices) == 2_072
    for r in db_obs:
        expected = weekly_prices[(r["retailer"], r["variant"], r["week_label"])]
        assert r["price"] == pytest.approx(expected), tuple(r)


def test_duplicate_date_not_double_weighted(conn, raw_xl):
    # the raw extract duplicates 2022-02-28 (week 2022W22) for 15 pairs; the
    # stored weekly mean must weight that day once
    p = raw_xl.parse("Pricing Data", header=0)
    wk22 = p[(p["YEAR_WEEK"] == 202222) & (p["Retailer"] == "Retailer R4")
             & (p["Variant"] == "Variant V1") & (p["Price"] > 0)]
    assert wk22["Date"].duplicated().any()  # the quirk is really there
    expected = wk22.drop_duplicates("Date")["Price"].mean()
    got = q1(conn, "SELECT price FROM prices WHERE retailer = 'Retailer R4'"
                   " AND variant = 'Variant V1' AND week_label = '2022W22'")
    assert got == pytest.approx(expected)


def test_peer_filled_prices_match_peer_mean(conn, weekly_prices):
    filled = conn.execute(
        "SELECT retailer, variant, week_label, price FROM prices"
        " WHERE is_filled = 1").fetchall()
    assert len(filled) == 74
    for r in filled:
        peers = [weekly_prices[(peer, r["variant"], r["week_label"])]
                 for peer in RETAILERS
                 if (peer, r["variant"], r["week_label"]) in weekly_prices]
        assert peers, tuple(r)              # a peer-filled row must have peers
        assert (r["retailer"], r["variant"], r["week_label"]) not in weekly_prices
        assert r["price"] == pytest.approx(sum(peers) / len(peers)), tuple(r)
    # the 24 all-zero R2 placeholder weeks (D21) must each be peer-filled
    for week in ("2022W28", "2022W42", "2023W02", "2023W26", "2023W41", "2024W02"):
        for variant in ("Variant V1", "Variant V2", "Variant V3", "Variant V4"):
            row = conn.execute(
                "SELECT is_filled FROM prices WHERE retailer = 'Retailer R2'"
                " AND variant = ? AND week_label = ?", (variant, week)).fetchone()
            assert row is not None and row["is_filled"] == 1, (variant, week)


def test_carried_forward_prices(conn, weekly_prices):
    carried = conn.execute(
        "SELECT p.retailer, p.variant, p.week_label, p.price, c.week_index"
        " FROM prices p JOIN calendar c ON c.week_label = p.week_label"
        " WHERE p.is_filled = 2").fetchall()
    assert len(carried) == 53
    for r in carried:
        # no same-week peer may exist (else it would be peer-filled)...
        assert not any((peer, r["variant"], r["week_label"]) in weekly_prices
                       for peer in RETAILERS), tuple(r)
        # ...and the price equals the pair's previous week in the DB
        prev = conn.execute(
            "SELECT p.price FROM prices p JOIN calendar c"
            " ON c.week_label = p.week_label WHERE p.retailer = ?"
            " AND p.variant = ? AND c.week_index = ?",
            (r["retailer"], r["variant"], r["week_index"] - 1)).fetchone()
        assert prev is not None and r["price"] == pytest.approx(prev["price"])


def test_variant_parsing(conn):
    rows = {r["variant"]: dict(r) for r in
            conn.execute("SELECT * FROM variants").fetchall()}
    assert len(rows) == 12
    for v in ("Variant V1", "Variant V2", "Variant V3", "Variant V4"):
        assert rows[v]["classification"] == "core"
        assert rows[v]["cap_total"] is None

    for v, cap in [("Variant V5", 38_000), ("Variant V6", 50_000),
                   ("Variant V7", 22_000)]:
        assert rows[v]["classification"] == "one_time_deal"
        assert rows[v]["exclusive_retailer"] == "Retailer R4"
        assert rows[v]["cap_total"] == cap
        assert rows[v]["release_week"] is None

    expected_exclusives = {
        "Variant V8": ("Retailer R3", "2023W02", 13_832, 0, 0),
        "Variant V9": ("Retailer R4", "2022W48", 20_058, 0, 0),
        "Variant V10": ("Retailer R2", "2023W49", 55_332, 2_075, 0),
        "Variant V11": ("Retailer R4", "2023W49", 19_020, 3_458, 1_211),
    }
    for v, (retailer, release, g1, g2, g35) in expected_exclusives.items():
        assert rows[v]["classification"] == "exclusive", v
        assert rows[v]["exclusive_retailer"] == retailer, v
        assert rows[v]["release_week"] == release, v
        assert rows[v]["cap_g1"] == g1, v
        assert rows[v]["cap_g2"] == g2, v
        assert rows[v]["cap_g35"] == g35, v
        assert rows[v]["cap_total"] == g1 + g2 + g35, v

    v12 = rows["Variant V12"]
    assert v12["classification"] == "one_time_drop"
    assert v12["eol_week"] == "2022W14"
    assert v12["cap_total"] == 1_000


def test_seasonality_reconciles_to_sheet(conn, raw_xl):
    s = raw_xl.parse("Strong Seasonality Weeks", header=None)
    expected = set()
    for col in range(1, s.shape[1], 2):
        year = int(s.iat[0, col])
        for r in range(2, s.shape[0]):
            event = s.iat[r, 0]
            if pd.isna(event):
                continue
            cy, wk = str(s.iat[r, col + 1]).strip().split("_")
            expected.add((str(event).strip(), year, f"{int(cy)}W{int(wk):02d}"))
    got = {(r["event"], r["fiscal_year"], r["week_label"]) for r in
           conn.execute("SELECT event, fiscal_year, week_label FROM seasonality")}
    assert len(expected) == 52 and got == expected

    assert q1(conn, "SELECT COUNT(DISTINCT event) FROM seasonality") == 13
    # exactly the two contradictory fiscal-2024 Promo Q4 rows are flagged
    bad = conn.execute("SELECT event, fiscal_year FROM seasonality"
                       " WHERE is_consistent = 0 ORDER BY event").fetchall()
    assert [(r["event"], r["fiscal_year"]) for r in bad] == [
        ("Promo Q4", 2024), ("Promo Q4 Rollover", 2024)]
    # 11 fiscal-2021 events precede the data window + those 2 exceed it
    assert q1(conn, "SELECT COUNT(*) FROM seasonality s LEFT JOIN calendar c"
                    " ON c.week_label = s.week_label"
                    " WHERE c.week_label IS NULL") == 13
    assert q1(conn, "SELECT week_label FROM seasonality"
                    " WHERE event = 'XMAS' AND fiscal_year = 2023") == "2023W13"
    # horizon holidays exist for the forecast layer
    assert q1(conn, "SELECT COUNT(*) FROM seasonality s JOIN calendar c"
                    " ON c.week_label = s.week_label WHERE c.is_horizon = 1") > 0


def test_params_full_double_entry(conn):
    # complete literal transcription, typed independently of params.py —
    # a typo in either place fails here (docs D12/D19; Objective sheet)
    assert dict(conn.execute("SELECT key, value FROM params").fetchall()) == {
        "first_actual_week": "2021W41",
        "last_actual_week": "2023W39",
        "horizon_start": "2023W40",
        "horizon_end": "2024W39",
        "holdout_start": "2023W27",
        "wos_kanban": "6",
        "wos_sea_freight": "6",
        "wos_kanban_sea_target": "12",
        "wos_channel_target": "13",
        "quarterly_capacity_cap": "224000",
        "weekly_capacity_cap": "17280",
        "packout_slots_per_week": "4",
        "scenario_variants": "Variant V2,Variant V4",
        "scenario_weekly_cap": "4500",
        "scenario_n_weeks": "6",
        "oem_location": "Thailand",
    }


def test_freight_full_double_entry(conn):
    rows = [tuple(r) for r in conn.execute(
        "SELECT mode, geo, lead_time_weeks, cost_per_unit FROM freight"
        " ORDER BY mode, geo")]
    assert rows == [
        ("Air", "ANY", 1, 7.0),
        ("Fast Boat Ocean", "Geo G1", 5, 3.5),
        ("Ground", "Geo G4", 1, 2.5),
        ("Standard Ocean", "Geo G1", 8, 2.0),
        ("Standard Ocean", "Geo G2", 11, 2.5),
    ]


def test_series_grain_unique(conn):
    dupes = q1(conn, "SELECT COUNT(*) FROM (SELECT channel, geo, customer,"
                     " variant, sku FROM series GROUP BY 1,2,3,4,5"
                     " HAVING COUNT(*) > 1)")
    assert dupes == 0
    # the known D20 quirk: exactly 4 'Region 2_' bucket series, PPN derived
    quirk = conn.execute(
        "SELECT variant, ppn FROM series WHERE sku = 'Region 2_'"
        " ORDER BY ppn").fetchall()
    assert [(r["variant"], r["ppn"]) for r in quirk] == [
        ("Variant V1", 1), ("Variant V2", 2),
        ("Variant V3", 3), ("Variant V4", 4)]
