"""V2+V4 shared-enclosure shortage scenario (brief §3.3, docs D13).

The supplier caps combined V2+V4 production at 4,500 u/week for the first six
weeks of CQ+1 (2023W40..2023W45). The scenario re-runs the identical MILP with
that one extra constraint; the allocation between V2 and V4 emerges from the
WOS-equalizing objective (scarce units flow to whichever variant is closer to
running out) rather than a hand-picked split — and is reported explicitly.

Both plans live side by side in the same tables (plan_id 'baseline' vs
'scenario'), so the UI diffs them with plain SQL; diff_summary() computes the
headline deltas the brief asks for.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from . import db, mps, params

SCENARIO_CAPS = [(params.SCENARIO_VARIANTS,
                  range(params.SCENARIO_N_WEEKS),
                  float(params.SCENARIO_WEEKLY_CAP))]
V2, V4 = params.SCENARIO_VARIANTS


def diff_summary(conn: sqlite3.Connection, base: str = "baseline",
                 scen: str = "scenario") -> dict:
    q = conn.execute

    def one(sql, *args):
        return q(sql, args).fetchone()[0] or 0.0

    # weekly allocation of the scarce 4,500 units
    allocation = []
    for w in range(params.SCENARIO_N_WEEKS):
        label = mps.week_label(w)
        row = {"week": label}
        for plan, tag in ((base, "base"), (scen, "scen")):
            for v, k in ((V2, "v2"), (V4, "v4")):
                row[f"{k}_{tag}"] = one(
                    "SELECT SUM(production) FROM mps WHERE plan_id = ?"
                    " AND variant = ? AND week_label = ?", plan, v, label)
        row["combined_scen"] = row["v2_scen"] + row["v4_scen"]
        allocation.append(row)

    def totals(plan):
        return {
            "production": one("SELECT SUM(production) FROM mps"
                              " WHERE plan_id = ?", plan),
            "freight": one("SELECT SUM(cost) FROM shipments"
                           " WHERE plan_id = ?", plan),
            "short": one("SELECT SUM(short_direct + short_ch3)"
                         " FROM inventory WHERE plan_id = ?", plan),
        }

    t_base, t_scen = totals(base), totals(scen)

    # stockout weeks per SKU (any unmet demand that week)
    stockouts = {}
    for plan in (base, scen):
        for r in q("SELECT variant, COUNT(DISTINCT week_label) AS n"
                   " FROM inventory WHERE plan_id = ?"
                   " AND short_direct + short_ch3 > 0.5 GROUP BY variant",
                   (plan,)):
            stockouts.setdefault(r["variant"], {})[plan] = r["n"]

    # supply-WOS impact per geo, V2/V4 only (the disruption's blast radius):
    # how many variant-geo-weeks got materially worse, and the average loss
    wos_hit = []
    for r in q("SELECT b.geo,"
               " SUM(CASE WHEN s.wos_supply < b.wos_supply - 0.5 THEN 1"
               " ELSE 0 END) AS weeks_worse,"
               " ROUND(AVG(b.wos_supply - s.wos_supply), 2) AS avg_wos_loss"
               " FROM inventory b JOIN inventory s ON s.plan_id = ?"
               " AND s.variant = b.variant AND s.geo = b.geo"
               " AND s.week_label = b.week_label"
               " WHERE b.plan_id = ? AND b.variant IN (?, ?)"
               " GROUP BY b.geo ORDER BY avg_wos_loss DESC",
               (scen, base, V2, V4)):
        wos_hit.append(dict(r))

    # reseller (Ch3) inventory drift for V2/V4 by week, and recovery: the
    # last week where the scenario's combined V2+V4 supply position still
    # trails baseline by more than 1%
    drift = q("SELECT b.week_label, SUM(s.ch3_inventory - b.ch3_inventory)"
              " AS d, SUM(s.on_hand + s.in_transit)"
              " - SUM(b.on_hand + b.in_transit) AS pos_d,"
              " SUM(b.on_hand + b.in_transit) AS pos_b"
              " FROM inventory b JOIN inventory s ON s.plan_id = ?"
              " AND s.variant = b.variant AND s.geo = b.geo"
              " AND s.week_label = b.week_label"
              " WHERE b.plan_id = ? AND b.variant IN (?, ?)"
              " GROUP BY b.week_label ORDER BY b.week_label",
              (scen, base, V2, V4)).fetchall()
    last_trailing = None
    for r in drift:
        if r["pos_b"] > 0 and r["pos_d"] < -0.01 * r["pos_b"]:
            last_trailing = r["week_label"]
    ch3_drift = [{"week": r["week_label"], "ch3_delta": round(r["d"])}
                 for r in drift[:16]]

    return {
        "allocation": allocation,
        "volume_delta": t_scen["production"] - t_base["production"],
        "freight_delta": t_scen["freight"] - t_base["freight"],
        "short_delta": t_scen["short"] - t_base["short"],
        "baseline": t_base, "scenario": t_scen,
        "stockout_weeks": stockouts,
        "wos_hit_by_geo": wos_hit,
        "ch3_drift_first_weeks": ch3_drift,
        "last_trailing_week": last_trailing,
    }


def run(db_path: str | Path) -> dict:
    info = mps.run(db_path, plan_id="scenario", extra_prod_caps=SCENARIO_CAPS)
    conn = db.connect(db_path)
    try:
        summary = diff_summary(conn)
    finally:
        conn.close()
    return {**info, **summary}
