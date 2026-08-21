"""Human-friendly spot checks: is what the pipeline claims actually true?

Run (from the repo root, inside the avathon conda env):

    python engine/verify.py

Every check is INDEPENDENT of the pipeline code: totals are recomputed
straight from program_z.xlsx with pandas, and plan constraints are re-checked
with plain SQL — no planz modules are imported. Expected values are hard-coded
here on purpose (double-entry): if code and expectations drift apart, this
script fails loudly.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "program_z.xlsx"
DB = ROOT / "planz.db"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str):
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name:<42} {detail}")


def main() -> int:
    print("Program Z — independent spot checks")
    print("=" * 72)

    if not DB.exists():
        print("planz.db not found — run: python engine/run_pipeline.py "
              "--ingest --forecast --mps")
        return 1

    conn = sqlite3.connect(DB)
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731

    # --- 1. raw data -> database reconciliation (recomputed from Excel) ---
    print("\n1. Excel -> database reconciliation")
    d = pd.read_excel(XLSX, sheet_name="Data - 104 weeks")
    weeks = [c for c in d.columns
             if isinstance(c, str) and len(c) == 7 and c[4] == "W"]
    v1 = d[(d["Variant Desc."] == "Variant V1")
           & (d["Values"] == "Net Sell-Through")][weeks].sum().sum()
    check("V1 lifetime sell-through (Excel)", v1 == 581_325,
          f"Excel says {v1:,.0f}, expected 581,325")
    db_v1 = q("SELECT SUM(a.units) FROM actuals a JOIN series s"
              " USING (series_id) WHERE s.variant = 'Variant V1'"
              " AND a.metric = 'ST'")
    check("V1 lifetime sell-through (database)", abs(db_v1 - v1) < 0.5,
          f"database says {db_v1:,.0f} — matches Excel" if abs(db_v1 - v1) < 0.5
          else f"database says {db_v1:,.0f} != Excel {v1:,.0f}")
    n_rows = q("SELECT COUNT(*) FROM actuals")
    check("actuals row count", n_rows == 32_032,
          f"{n_rows:,} rows = 154 series x 104 weeks x 2 metrics")

    # --- 2. forecast sanity ---
    print("\n2. Forecast sanity")
    n_fc = q("SELECT COUNT(*) FROM forecast")
    check("forecast size", n_fc == 124 * 52,
          f"{n_fc:,} rows = 124 series x 52 weeks")
    bad_q = q("SELECT COUNT(*) FROM forecast WHERE p10 > p50 OR p50 > p90"
              " OR p10 < 0")
    check("uncertainty bands ordered (P10<=P50<=P90)", bad_q == 0,
          f"{bad_q} violations")
    v12 = q("SELECT SUM(ABS(p50)) FROM forecast WHERE variant = 'Variant V12'")
    check("dead variant V12 forecast is zero", v12 == 0, f"sum = {v12:,.0f}")
    v10 = q("SELECT SUM(p50) FROM forecast WHERE variant = 'Variant V10'")
    check("V10 launch ramps to its deal volume", abs(v10 - 57_407) < 1,
          f"{v10:,.0f} vs committed 57,407")
    peak = conn.execute("SELECT week_label, SUM(p50) AS t FROM forecast"
                        " GROUP BY 1 ORDER BY t DESC LIMIT 1").fetchone()
    check("demand peaks in the holiday cluster", "2024W08" <= peak[0] <= "2024W13",
          f"peak week {peak[0]} ({peak[1]:,.0f} u)")
    scores = dict(conn.execute("SELECT model, wape FROM forecast_scores"
                               " WHERE scope_type = 'overall'").fetchall())
    ok = scores["xgb"] < scores["seasonal_naive"] < scores["naive"]
    check("model beats both baselines (holdout WAPE)", ok,
          f"xgb {scores['xgb']:.1%} < snaive {scores['seasonal_naive']:.1%}"
          f" < naive {scores['naive']:.1%}")

    # --- 3. plan hard constraints (re-checked with plain SQL) ---
    print("\n3. Plan hard constraints (plain-SQL recheck)")
    wk = q("SELECT MAX(t) FROM (SELECT SUM(production) AS t FROM mps"
           " WHERE plan_id = 'baseline' GROUP BY week_label)")
    check("weekly capacity 17,280", wk <= 17_280.5,
          f"busiest week: {wk:,.0f}")
    qt = q("SELECT MAX(t) FROM (SELECT SUM(m.production) AS t FROM mps m"
           " JOIN calendar c ON c.week_label = m.week_label"
           " WHERE m.plan_id = 'baseline' GROUP BY c.quarter_label)")
    check("quarterly capacity 224,000", qt <= 224_000.5,
          f"busiest quarter: {qt:,.0f}")
    slots = q("SELECT MAX(t) FROM (SELECT SUM(packout) AS t FROM mps"
              " WHERE plan_id = 'baseline' GROUP BY week_label)")
    check("max 4 variants packed out per week", slots <= 4,
          f"busiest week uses {slots} slots")
    v5 = q("SELECT SUM(production) FROM mps WHERE plan_id = 'baseline'"
           " AND variant = 'Variant V5'")
    check("V5 stays within its remaining volume", v5 <= 2_484.5,
          f"planned {v5:,.0f} vs 2,484 left of the 38k deal")
    fails = q("SELECT COUNT(*) FROM validation WHERE plan_id = 'baseline'"
              " AND status = 'FAIL'")
    n_checks = q("SELECT COUNT(*) FROM validation WHERE plan_id = 'baseline'")
    check("pipeline's own validators", fails == 0 and n_checks >= 9,
          f"{n_checks - fails}/{n_checks} PASS")

    conn.close()
    n_ok = sum(1 for _, ok, _ in RESULTS if ok)
    print("\n" + "=" * 72)
    print(f"{n_ok}/{len(RESULTS)} checks passed"
          + ("" if n_ok == len(RESULTS) else "  <-- INVESTIGATE FAILURES"))
    return 0 if n_ok == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
