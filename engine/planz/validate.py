"""Independent post-solve constraint validation (PRD F3.2): every hard
constraint is re-checked from the persisted tables, never trusting the
solver's status. Results are written to the `validation` table; the pipeline
fails on any FAIL row.

Independence boundary: these checks are independent of the SOLVER (they
recompute from persisted rows), but the volume-cap and balance-replay checks
reuse mps.py's demand/opening-state loaders — a misreading of the D23 cap
semantics would fail identically in both places. That residual blind spot is
covered by the double-entry literals in the test suite."""
from __future__ import annotations

import sqlite3

from . import mps, params

TOL = 0.5          # units; CBC solutions are continuous, tolerance is generous


def run_checks(conn: sqlite3.Connection, plan_id: str,
               extra_prod_caps=None, mode_blocks=None,
               demand_mults=None) -> list[tuple]:
    checks: list[tuple] = []

    def add(name: str, ok: bool, detail: str):
        checks.append((plan_id, name, "PASS" if ok else "FAIL", detail))

    prod = {}          # (variant, week) -> units
    packed = {}        # week -> set of packed variants
    for r in conn.execute(
            "SELECT variant, week_label, production, packout FROM mps"
            " WHERE plan_id = ?", (plan_id,)):
        prod[(r["variant"], r["week_label"])] = r["production"]
        if r["packout"]:
            packed.setdefault(r["week_label"], set()).add(r["variant"])
        if r["production"] > TOL and not r["packout"]:
            packed.setdefault("__violation__", set()).add(r["variant"])

    weeks = sorted({w for _, w in prod})
    weekly = {w: sum(u for (v, wk), u in prod.items() if wk == w)
              for w in weeks}

    worst = max(weekly.values(), default=0.0)
    add("weekly_capacity", worst <= params.WEEKLY_CAPACITY_CAP + TOL,
        f"max weekly production {worst:,.0f} vs cap"
        f" {params.WEEKLY_CAPACITY_CAP:,}")

    qtr = {}
    for r in conn.execute(
            "SELECT c.quarter_label AS q, SUM(m.production) AS u FROM mps m"
            " JOIN calendar c ON c.week_label = m.week_label"
            " WHERE m.plan_id = ? GROUP BY 1", (plan_id,)):
        qtr[r["q"]] = r["u"]
    add("quarterly_capacity",
        all(u <= params.QUARTERLY_CAPACITY_CAP + TOL for u in qtr.values()),
        "; ".join(f"{q}: {u:,.0f}/{params.QUARTERLY_CAPACITY_CAP:,}"
                  for q, u in sorted(qtr.items())))

    max_slots = max((len(vs) for w, vs in packed.items()
                     if w != "__violation__"), default=0)
    add("packout_slots", max_slots <= params.PACKOUT_SLOTS_PER_WEEK,
        f"max variants packed in a week: {max_slots}")
    add("packout_linkage", "__violation__" not in packed,
        "production requires a pack-out slot")

    ship_sum = {}
    for r in conn.execute(
            "SELECT variant, week_label, SUM(units) AS u FROM shipments"
            " WHERE plan_id = ? GROUP BY 1, 2", (plan_id,)):
        ship_sum[(r["variant"], r["week_label"])] = r["u"]
    max_diff = max((abs(ship_sum.get(k, 0.0) - u) for k, u in prod.items()),
                   default=0.0)
    add("ship_conservation", max_diff <= TOL,
        f"max |shipments - production| per variant-week: {max_diff:.3f}")

    neg = conn.execute(
        "SELECT COUNT(*) FROM inventory WHERE plan_id = ? AND"
        " (on_hand < -? OR in_transit < -? OR ch3_inventory < -?)",
        (plan_id, TOL, TOL, TOL)).fetchone()[0]
    add("nonnegative_inventory", neg == 0, f"{neg} negative inventory cells")

    # volume caps: cumulative production per capped variant (D23)
    pairs, d_dir, d_ch3 = mps.load_demand(conn)
    # the plan was solved against the shocked cube — replay against the same
    mps.apply_demand_mults(pairs, d_dir, d_ch3, demand_mults)
    d_tot = {k: d_dir[k] + d_ch3[k] for k in pairs}
    caps = mps.production_caps(conn, d_tot)
    breaches = []
    for v, cap in caps.items():
        tot = sum(u for (vv, w), u in prod.items() if vv == v)
        if tot > cap + TOL:
            breaches.append(f"{v}: {tot:,.0f} > {cap:,.0f}")
    add("volume_caps", not breaches, "; ".join(breaches) or
        f"{len(caps)} capped variants within remaining volume")

    # balance replay: re-derive OH/IT/C3 trajectories from shipments +
    # forecast demand + opening state and compare to the persisted inventory
    # rows — catches lead-time indexing bugs, lost/double-counted pipeline
    # stock, shorts exceeding demand, and extraction errors the solver's own
    # echoed values cannot reveal
    modes = mps.freight_modes(conn)
    launched = mps.launched_variants(conn)
    oh0, c30, pipe, it0 = mps.opening_state(
        pairs, d_tot, d_ch3, modes, launched)
    ships = {}
    for r in conn.execute(
            "SELECT s.variant, s.geo, c.week_index - 144 AS w, s.mode,"
            " SUM(s.units) AS u FROM shipments s JOIN calendar c"
            " ON c.week_label = s.week_label WHERE s.plan_id = ?"
            " GROUP BY 1, 2, 3, 4", (plan_id,)):
        ships[(r["variant"], r["geo"], r["w"], r["mode"])] = r["u"]
    inv = {}
    for r in conn.execute(
            "SELECT i.variant, i.geo, c.week_index - 144 AS w, i.on_hand,"
            " i.in_transit, i.ch3_inventory, i.short_direct, i.short_ch3"
            " FROM inventory i JOIN calendar c ON c.week_label = i.week_label"
            " WHERE i.plan_id = ?", (plan_id,)):
        inv[(r["variant"], r["geo"], r["w"])] = r

    worst_bal, bad_short = 0.0, 0
    if inv:
        for k in pairs:
            v, g = k
            leads = {m: lead for m, lead, _ in modes[g]}
            oh, itr, c3v = oh0[k], it0[k], c30[k]
            for w in range(mps.H):
                row = inv.get((v, g, w))
                if row is None:
                    continue
                arr = sum(ships.get((v, g, w - lead, m), 0.0)
                          for m, lead in leads.items())
                sent = sum(ships.get((v, g, w, m), 0.0) for m in leads)
                s12, s3 = row["short_direct"], row["short_ch3"]
                if s12 > d_dir[k][w] + TOL or s3 > d_ch3[k][w] + TOL:
                    bad_short += 1
                # si3 implied by the persisted channel trajectory
                si3 = row["ch3_inventory"] - c3v + (d_ch3[k][w] - s3)
                exp_oh = oh + arr + pipe[k][w] - (d_dir[k][w] - s12) - si3
                exp_it = itr + sent - arr - pipe[k][w]
                worst_bal = max(worst_bal,
                                abs(row["on_hand"] - exp_oh),
                                abs(row["in_transit"] - exp_it),
                                -si3 if si3 < -TOL else 0.0)
                oh, itr, c3v = row["on_hand"], row["in_transit"], row["ch3_inventory"]
    add("balance_replay", worst_bal <= TOL,
        f"max |persisted - replayed| inventory: {worst_bal:.3f}")
    add("shorts_within_demand", bad_short == 0,
        f"{bad_short} short cells exceed forecast demand")

    # freight disruptions: no shipment may use a blocked (geo, mode, week)
    for bi, (g, m, ws) in enumerate(mode_blocks or []):
        labels = [mps.week_label(w) for w in ws]
        ph = ",".join("?" for _ in labels)
        n_bad = conn.execute(
            f"SELECT COUNT(*) FROM shipments WHERE plan_id = ? AND geo = ?"
            f" AND mode = ? AND week_label IN ({ph})",
            (plan_id, g, m, *labels)).fetchone()[0]
        add(f"mode_block_{bi}", n_bad == 0,
            f"{n_bad} shipments on blocked {m}/{g}")

    # scenario extra caps (combined production per listed week)
    for ci, (vs, ws, cap) in enumerate(extra_prod_caps or []):
        worst_extra = 0.0
        for w in ws:
            label = mps.week_label(w)
            worst_extra = max(worst_extra,
                              sum(prod.get((v, label), 0.0) for v in vs))
        add(f"extra_cap_{ci}", worst_extra <= cap + TOL,
            f"max combined {'+'.join(v[-3:] for v in vs)} production"
            f" {worst_extra:,.0f} vs cap {cap:,.0f}")

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM validation WHERE plan_id = ?", (plan_id,))
        conn.executemany("INSERT INTO validation VALUES (?,?,?,?)", checks)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return checks
