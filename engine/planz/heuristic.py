"""Constructive greedy MPS — the second planning method (docs D26).

This is the plan a careful human planner would build by hand, week by week,
with no optimizer: look 12 weeks ahead, find the variants furthest below
their coverage targets, give the 4 pack-out slots to the neediest, split
each build across geos by shortfall, and ship on the cheapest mode that
still arrives before the projected run-out.

It exists as a cross-check and an explainability baseline for the MILP:
both methods write the same tables, pass the same independent validators,
and are compared head-to-head (freight cost, unmet demand, buffer health).
Every step here is a sentence; the MILP's advantage over this method is
therefore measurable, not asserted.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

from . import db, mps, params, wos

H = mps.H
QUARTER_START = {0, 13, 26, 39}


def solve(conn: sqlite3.Connection, plan_id: str = "heuristic",
          extra_prod_caps=None, demand_mults=None, mode_blocks=None) -> dict:
    pairs, d_dir, d_ch3 = mps.load_demand(conn)
    mps.apply_demand_mults(pairs, d_dir, d_ch3, demand_mults)
    blocked = {(g, m, w) for g, m, ws in (mode_blocks or []) for w in ws}
    d_tot = {k: d_dir[k] + d_ch3[k] for k in pairs}
    variants = sorted({v for v, g in pairs},
                      key=lambda v: int(v.split("V")[-1]))
    modes = mps.freight_modes(conn)
    launched = mps.launched_variants(conn)
    vol_caps = mps.production_caps(conn, d_tot)
    oh0, c30, pipe, it0 = mps.opening_state(pairs, d_tot, d_ch3, modes, launched)

    # per-week combined caps from the scenario hook
    week_caps: dict[int, list[tuple[tuple[str, ...], float]]] = {}
    for vs, ws, cap in (extra_prod_caps or []):
        for w in ws:
            week_caps.setdefault(w, []).append((vs, cap))

    oh = {k: oh0[k] for k in pairs}
    c3 = {k: c30[k] for k in pairs}
    it = {k: it0[k] for k in pairs}
    arrivals = {k: np.zeros(H + 1) for k in pairs}   # scheduled from our ships
    vol_used = {v: 0.0 for v in variants}

    mps_rows, ship_rows, inv_rows = [], [], []
    quarterly_left = params.QUARTERLY_CAPACITY_CAP

    for w in range(H):
        if w in QUARTER_START:
            quarterly_left = params.QUARTERLY_CAPACITY_CAP

        # 1. receive: scheduled arrivals + the pre-horizon pipeline
        week_short12, week_short3 = {}, {}
        for k in pairs:
            arr = arrivals[k][w] + pipe[k][w]
            oh[k] += arr
            it[k] = max(0.0, it[k] - arr)
            # 2. serve direct (Ch1/2) demand from on-hand
            served = min(oh[k], d_dir[k][w])
            week_short12[k] = d_dir[k][w] - served
            oh[k] -= served
            # 3. channel: sell through from reseller stock, then refill it
            #    from on-hand toward the 13-WOS target
            sold = min(c3[k], d_ch3[k][w])
            week_short3[k] = d_ch3[k][w] - sold
            c3[k] -= sold
            tgt_c3 = wos.target_stock(d_ch3[k][w + 1:],
                                      params.WOS_CHANNEL_TARGET)
            si3 = min(oh[k], max(0.0, tgt_c3 - c3[k]))
            oh[k] -= si3
            c3[k] += si3

        # 4. production: rank variants by coverage shortfall vs the 12-WOS
        #    supply target, give slots to the neediest, allocate capacity
        #    proportionally to shortfall
        shortfall = {}
        geo_short = {}
        for v in variants:
            s_total = 0.0
            for g in [g for (vv, g) in pairs if vv == v]:
                k = (v, g)
                avail = [m for m in modes[g] if (g, m[0], w) not in blocked]
                if not avail:
                    continue                   # every mode blocked this week
                fastest = min(lead for _, lead, _ in avail)
                if w + fastest > H - 1:
                    continue                   # nothing can arrive in time
                tgt = wos.target_stock(d_tot[k][w + 1:],
                                       params.WOS_KANBAN_SEA_TARGET)
                gap = max(0.0, tgt - (oh[k] + it[k]))
                if gap > 0:
                    geo_short[k] = gap
                    s_total += gap
            cap_left = vol_caps.get(v, float("inf")) - vol_used[v]
            shortfall[v] = min(s_total, max(0.0, cap_left))

        chosen = sorted((v for v in variants if shortfall[v] > 0.5),
                        key=lambda v: -shortfall[v])[:params.PACKOUT_SLOTS_PER_WEEK]
        capacity = min(params.WEEKLY_CAPACITY_CAP, quarterly_left)
        total_need = sum(shortfall[v] for v in chosen)
        prod = {}
        for v in chosen:
            share = capacity * shortfall[v] / total_need if total_need else 0.0
            prod[v] = min(shortfall[v], share)
        # combined-cap constraint (scenario hook): scale the capped group down
        for vs, cap in week_caps.get(w, []):
            group = [v for v in vs if prod.get(v, 0.0) > 0]
            combined = sum(prod[v] for v in group)
            if combined > cap:
                for v in group:
                    prod[v] *= cap / combined

        # 5. ship each build across geos by shortfall; cheapest mode that
        #    lands before the projected run-out, else the fastest usable
        for v in variants:
            units = prod.get(v, 0.0)
            mps_rows.append((plan_id, v, mps.week_label(w), units,
                             int(units > 0.5)))
            if units <= 0:
                continue
            vol_used[v] += units
            quarterly_left -= units
            keys = [k for k in geo_short if k[0] == v]
            g_total = sum(geo_short[k] for k in keys)
            for k in keys:
                v_, g = k
                qty = units * geo_short[k] / g_total if g_total else 0.0
                if qty <= 0:
                    continue
                runout = wos.run_out_wos(oh[k] + it[k], d_tot[k][w + 1:])
                usable = [m for m in modes[g] if w + m[1] <= H - 1
                          and (g, m[0], w) not in blocked]
                if not usable:
                    continue
                fitting = [m for m in usable if m[1] <= max(1.0, runout)]
                mode = (min(fitting, key=lambda m: m[2]) if fitting
                        else min(usable, key=lambda m: m[1]))
                name, lead, cost = mode
                arrivals[k][w + lead] += qty
                it[k] += qty
                ship_rows.append((plan_id, v_, g, mps.week_label(w), name,
                                  qty, qty * cost))

        # 6. record end-of-week state
        for k in pairs:
            v, g = k
            inv_rows.append((
                plan_id, v, g, mps.week_label(w), oh[k], it[k], c3[k],
                wos.run_out_wos(oh[k] + it[k], d_tot[k][w + 1:]),
                wos.run_out_wos(c3[k], d_ch3[k][w + 1:]),
                week_short12[k], week_short3[k]))

    total_short = sum(r[-2] + r[-1] for r in inv_rows)
    freight = sum(r[6] for r in ship_rows)
    return {"mps": mps_rows, "shipments": ship_rows, "inventory": inv_rows,
            "freight_cost": freight, "total_short": total_short,
            "total_production": sum(r[3] for r in mps_rows)}


def run(db_path: str | Path, plan_id: str = "heuristic",
        extra_prod_caps=None, demand_mults=None, mode_blocks=None) -> dict:
    from . import validate
    conn = db.connect(db_path)
    try:
        sol = solve(conn, plan_id, extra_prod_caps=extra_prod_caps,
                    demand_mults=demand_mults, mode_blocks=mode_blocks)
        mps.persist_plan(conn, plan_id, sol)
        checks = validate.run_checks(conn, plan_id,
                                     extra_prod_caps=extra_prod_caps,
                                     mode_blocks=mode_blocks,
                                     demand_mults=demand_mults)
        failed = [c for c in checks if c[2] == "FAIL"]
        if failed:
            raise RuntimeError(f"heuristic plan failed validation: {failed}")
        return {k: sol[k] for k in ("freight_cost", "total_short",
                                    "total_production")}
    finally:
        conn.close()


def compare(db_path: str | Path, a: str = "baseline",
            b: str = "heuristic") -> list[tuple]:
    """Head-to-head table between two stored plans."""
    conn = db.connect(db_path)
    try:
        out = []
        for plan in (a, b):
            row = conn.execute(
                "SELECT (SELECT SUM(production) FROM mps WHERE plan_id=:p),"
                " (SELECT SUM(cost) FROM shipments WHERE plan_id=:p),"
                " (SELECT SUM(short_direct+short_ch3) FROM inventory"
                "  WHERE plan_id=:p)", {"p": plan}).fetchone()
            wos_rows = conn.execute(
                "SELECT wos_supply, wos_channel FROM inventory"
                " WHERE plan_id=?", (plan,)).fetchall()
            n = len(wos_rows)
            med_s = sorted(r["wos_supply"] for r in wos_rows)[n // 2] if n else None
            med_c = sorted(r["wos_channel"] for r in wos_rows)[n // 2] if n else None
            out.append((plan, row[0] or 0, row[1] or 0, row[2] or 0,
                        med_s, med_c))
        return out
    finally:
        conn.close()
