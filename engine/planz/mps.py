"""Master Production Schedule + pack-out plan (docs D3, D12, D24, PRD F3).

MILP over the 52-week horizon at variant (production) and variant x geo
(shipping/inventory) grain, solved with PuLP + CBC.

Hard constraints:
- weekly capacity 17,280 u; quarterly capacity 224,000 u
- at most 4 variants packed out in any week (binary slot vars)
- inventory balances, non-negativity
- production caps for volume-capped variants (D23)
- optional extra weekly caps (the V2+V4 enclosure scenario, phase 4)

Soft goals (objective): unmet demand >> WOS-target shortfalls > freight cost
> holding cost. WOS targets are linearized as target stock = sum of the next
12 (supply) / 13 (channel) weeks of demand — exactly the run-out convention.

Two-tier inventory per variant x geo:
- OH (on-hand at destination DC) + IT (in transit) = supply position,
  target 12 WOS of total demand (Kanban 6 + Sea Freight 6);
- C3 (Channel-3 reseller stock), target 13 WOS of Ch3 demand. Channels 1&2
  ship from OH directly (SI = ST, no channel stock).

Opening state (D24, client question): launched variants start at target
(OH = 6 WOS, C3 = 13 WOS) with a steady-state arrival pipeline during the
first lead-time weeks; unlaunched variants (V10/V11) start empty.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pulp

from . import db, lifecycle, params, wos
from . import features as ft

H = 52                              # horizon weeks
EXT = 16                            # lookahead padding beyond horizon
GEOS = ["Geo G1", "Geo G2", "Geo G3", "Geo G4", "Geo G5"]
QUARTERS = [range(0, 13), range(13, 26), range(26, 39), range(39, 52)]

# objective weights ($/unit or $/unit-week); rationale in docstring
W_SHORT = 1000.0
W_DEV_SUPPLY = 2.0
W_DEV_CHANNEL = 3.0
W_HOLD_OH = 0.05
W_HOLD_C3 = 0.02

EPS = 1e-4


def week_label(w: int) -> str:
    return ft.label_of(104 + w)


# ---------------- data loading ----------------

def load_demand(conn: sqlite3.Connection):
    """P50 demand cube split into direct (Ch1+Ch2) and reseller (Ch3) parts.
    Returns (pairs, d_direct, d_ch3) with extended arrays of length H+EXT:
    weeks beyond the horizon repeat the same fiscal week one year earlier
    (the horizon starts exactly at a fiscal year boundary)."""
    d_direct: dict[tuple, np.ndarray] = {}
    d_ch3: dict[tuple, np.ndarray] = {}
    for r in conn.execute(
            "SELECT variant, geo, channel, week_label, p50 FROM forecast"):
        w = ft.offset_of(r["week_label"]) - 104
        if not 0 <= w < H:
            raise ValueError(f"forecast row outside horizon: {r['week_label']}")
        key = (r["variant"], r["geo"])
        tgt = d_ch3 if r["channel"] == "Channel 3" else d_direct
        if key not in tgt:
            tgt[key] = np.zeros(H + EXT)
        tgt[key][w] += r["p50"]
    pairs = sorted({k for k in set(d_direct) | set(d_ch3)
                    if (d_direct.get(k, np.zeros(1)).sum()
                        + d_ch3.get(k, np.zeros(1)).sum()) > 0})
    d_direct = {k: d_direct.get(k, np.zeros(H + EXT)) for k in pairs}
    d_ch3 = {k: d_ch3.get(k, np.zeros(H + EXT)) for k in pairs}
    for cube in (d_direct, d_ch3):
        for k in pairs:
            cube[k][H:] = cube[k][H - 52:H - 52 + EXT]   # seasonal extension
    return pairs, d_direct, d_ch3


def freight_modes(conn: sqlite3.Connection) -> dict[str, list[tuple[str, int, float]]]:
    """Per geo: the cost-Pareto set of [(mode, lead, cost)], cheapest first.
    A mode is kept only if it is strictly faster than every cheaper mode, so
    the solver sees the full cost/speed frontier (e.g. Geo G1 gets Standard
    Ocean, Fast Boat AND Air; Geo G4's Air is dominated by Ground and drops)."""
    options: dict[str, list[tuple[str, int, float]]] = {g: [] for g in GEOS}
    air = None
    for r in conn.execute("SELECT * FROM freight"):
        if r["geo"] == "ANY":
            air = (r["mode"], r["lead_time_weeks"], r["cost_per_unit"])
        else:
            options[r["geo"]].append(
                (r["mode"], r["lead_time_weeks"], r["cost_per_unit"]))
    modes = {}
    for g in GEOS:
        chosen, best_lead = [], None
        for m in sorted(options[g] + [air], key=lambda m: (m[2], m[1])):
            if best_lead is None or m[1] < best_lead:
                chosen.append(m)
                best_lead = m[1] if best_lead is None else min(best_lead, m[1])
        modes[g] = chosen
    return modes


def launched_variants(conn: sqlite3.Connection) -> set[str]:
    return {r["variant"] for r in conn.execute(
        "SELECT s.variant, SUM(ABS(a.units)) AS t FROM actuals a"
        " JOIN series s USING (series_id) GROUP BY s.variant HAVING t > 0")}


def production_caps(conn: sqlite3.Connection,
                    d_total: dict[tuple, np.ndarray]) -> dict[str, float]:
    """Variant-level production ceiling for volume-capped variants (D23):
    sum of stated forward volumes plus horizon demand in uncapped geos."""
    caps: dict[str, float] = {}
    capped_geos: dict[str, set] = {}
    for variant, geos, remaining in lifecycle.cap_specs(conn):
        caps[variant] = caps.get(variant, 0.0) + remaining
        capped_geos.setdefault(variant, set()).update(geos or GEOS)
    for (v, g), arr in d_total.items():
        if v in caps and g not in capped_geos[v]:
            caps[v] += float(arr[:H].sum())
    return caps


# ---------------- model ----------------

def opening_state(pairs, d_tot, d_ch3, modes, launched):
    """Opening inventories (D24), shared by solve() and the balance-replay
    validator: launched variants at OH = 6 WOS and channel = 13 WOS, with a
    steady-state pipeline arriving over the first primary-lead weeks."""
    oh0 = {k: (wos.target_stock(d_tot[k], params.WOS_KANBAN)
               if k[0] in launched else 0.0) for k in pairs}
    c30 = {k: (wos.target_stock(d_ch3[k], params.WOS_CHANNEL_TARGET)
               if k[0] in launched else 0.0) for k in pairs}
    pipe = {k: np.zeros(H) for k in pairs}
    for k in pairs:
        lead = modes[k[1]][0][1]
        if k[0] in launched:
            pipe[k][:lead] = d_tot[k][:lead]
    it0 = {k: float(pipe[k].sum()) for k in pairs}
    return oh0, c30, pipe, it0


def solve(conn: sqlite3.Connection, plan_id: str,
          extra_prod_caps: list[tuple[tuple[str, ...], range, float]] | None = None,
          time_limit: int = 600) -> dict:
    """Build and solve the MILP; returns solution tables as lists of rows.
    extra_prod_caps: [(variants, weeks, combined weekly cap)] — each listed
    week gets its own combined-production constraint (scenario hook)."""
    pairs, d_dir, d_ch3 = load_demand(conn)
    d_tot = {k: d_dir[k] + d_ch3[k] for k in pairs}
    variants = sorted({v for v, g in pairs},
                      key=lambda v: int(v.split("V")[-1]))
    modes = freight_modes(conn)
    launched = launched_variants(conn)
    prod_caps = production_caps(conn, d_tot)
    weeks = range(H)
    oh0, c30, pipe, it0 = opening_state(pairs, d_tot, d_ch3, modes, launched)

    prob = pulp.LpProblem(f"mps_{plan_id}", pulp.LpMinimize)

    prod = pulp.LpVariable.dicts("prod", (variants, weeks), lowBound=0)
    pack = pulp.LpVariable.dicts("pack", (variants, weeks), cat="Binary")
    # shipments that cannot arrive inside the horizon are forbidden — without
    # this bound the solver parks stock in transit near the horizon end just
    # to earn supply-position WOS credit for units that never land
    ship = {(v, g, w, m): pulp.LpVariable(
                f"ship_{v}_{g}_{w}_{m}", lowBound=0,
                upBound=(0 if w + lead > H - 1 else None))
            for (v, g) in pairs for w in weeks for m, lead, _ in modes[g]}
    oh = pulp.LpVariable.dicts("oh", (pairs, weeks), lowBound=0)
    it = pulp.LpVariable.dicts("it", (pairs, weeks), lowBound=0)
    c3 = pulp.LpVariable.dicts("c3", (pairs, weeks), lowBound=0)
    si3 = pulp.LpVariable.dicts("si3", (pairs, weeks), lowBound=0)
    sh12 = pulp.LpVariable.dicts("short12", (pairs, weeks), lowBound=0)
    sh3 = pulp.LpVariable.dicts("short3", (pairs, weeks), lowBound=0)
    dev_s = pulp.LpVariable.dicts("devS", (pairs, weeks), lowBound=0)
    dev_c = pulp.LpVariable.dicts("devC", (pairs, weeks), lowBound=0)

    # capacity, pack-out slots
    for w in weeks:
        prob += (pulp.lpSum(prod[v][w] for v in variants)
                 <= params.WEEKLY_CAPACITY_CAP), f"weekly_cap_{w}"
        prob += (pulp.lpSum(pack[v][w] for v in variants)
                 <= params.PACKOUT_SLOTS_PER_WEEK), f"slots_{w}"
        for v in variants:
            prob += prod[v][w] <= params.WEEKLY_CAPACITY_CAP * pack[v][w], \
                f"link_{v}_{w}"
    for qi, q in enumerate(QUARTERS):
        prob += (pulp.lpSum(prod[v][w] for v in variants for w in q)
                 <= params.QUARTERLY_CAPACITY_CAP), f"quarterly_cap_{qi}"

    # production = shipments, per variant-week
    for v in variants:
        v_geos = [g for (vv, g) in pairs if vv == v]
        for w in weeks:
            prob += (pulp.lpSum(ship[v, g, w, m] for g in v_geos
                                for m, _, _ in modes[g])
                     == prod[v][w]), f"conserve_{v}_{w}"

    # volume caps on production (D23)
    for v, cap in prod_caps.items():
        if v in variants:
            prob += (pulp.lpSum(prod[v][w] for w in weeks) <= cap), f"vol_cap_{v}"

    # scenario hook: combined weekly caps across variants
    for ci, (vs, ws, cap) in enumerate(extra_prod_caps or []):
        for w in ws:
            prob += (pulp.lpSum(prod[v][w] for v in vs if v in variants)
                     <= cap), f"extra_cap_{ci}_{w}"

    # inventory dynamics
    for k in pairs:
        v, g = k
        for w in weeks:
            arr_ours = pulp.lpSum(
                ship[v, g, w - lead, m] for m, lead, _ in modes[g]
                if w - lead >= 0)
            sent = pulp.lpSum(ship[v, g, w, m] for m, _, _ in modes[g])
            prev_oh = oh[k][w - 1] if w > 0 else oh0[k]
            prev_it = it[k][w - 1] if w > 0 else it0[k]
            prev_c3 = c3[k][w - 1] if w > 0 else c30[k]
            prob += (oh[k][w] == prev_oh + arr_ours + pipe[k][w]
                     - (d_dir[k][w] - sh12[k][w]) - si3[k][w]), f"oh_{v}_{g}_{w}"
            prob += (it[k][w] == prev_it + sent - arr_ours
                     - pipe[k][w]), f"it_{v}_{g}_{w}"
            prob += (c3[k][w] == prev_c3 + si3[k][w]
                     - (d_ch3[k][w] - sh3[k][w])), f"c3_{v}_{g}_{w}"
            prob += sh12[k][w] <= d_dir[k][w], f"sh12ub_{v}_{g}_{w}"
            prob += sh3[k][w] <= d_ch3[k][w], f"sh3ub_{v}_{g}_{w}"
            # WOS targets (linearized run-out): supply position & channel
            t_sup = float(d_tot[k][w + 1:w + 1 + params.WOS_KANBAN_SEA_TARGET].sum())
            t_ch = float(d_ch3[k][w + 1:w + 1 + params.WOS_CHANNEL_TARGET].sum())
            prob += oh[k][w] + it[k][w] + dev_s[k][w] >= t_sup, f"tsup_{v}_{g}_{w}"
            prob += c3[k][w] + dev_c[k][w] >= t_ch, f"tch_{v}_{g}_{w}"

    freight_cost = pulp.lpSum(
        ship[v, g, w, m] * cost
        for (v, g) in pairs for w in weeks for m, _, cost in modes[g])

    prob += (W_SHORT * pulp.lpSum(sh12[k][w] + sh3[k][w]
                                  for k in pairs for w in weeks)
             + W_DEV_SUPPLY * pulp.lpSum(dev_s[k][w] for k in pairs for w in weeks)
             + W_DEV_CHANNEL * pulp.lpSum(dev_c[k][w] for k in pairs for w in weeks)
             + freight_cost
             + W_HOLD_OH * pulp.lpSum(oh[k][w] for k in pairs for w in weeks)
             + W_HOLD_C3 * pulp.lpSum(c3[k][w] for k in pairs for w in weeks))

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit, gapRel=0.005)
    status = prob.solve(solver)
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"MPS solve failed: {pulp.LpStatus[status]}")

    # ---------------- extract ----------------
    val = pulp.value
    mps_rows, ship_rows, inv_rows = [], [], []
    for v in variants:
        for w in weeks:
            mps_rows.append((plan_id, v, week_label(w), val(prod[v][w]) or 0.0,
                             int(round(val(pack[v][w]) or 0))))
    for (v, g) in pairs:
        for w in weeks:
            for m, lead, cost in modes[g]:
                units = val(ship[v, g, w, m]) or 0.0
                if units > EPS:
                    ship_rows.append((plan_id, v, g, week_label(w), m,
                                      units, units * cost))
    total_short = 0.0
    for k in pairs:
        v, g = k
        for w in weeks:
            oh_v = val(oh[k][w]) or 0.0
            it_v = val(it[k][w]) or 0.0
            c3_v = val(c3[k][w]) or 0.0
            s12_v = val(sh12[k][w]) or 0.0
            s3_v = val(sh3[k][w]) or 0.0
            total_short += s12_v + s3_v
            inv_rows.append((
                plan_id, v, g, week_label(w), oh_v, it_v, c3_v,
                wos.run_out_wos(oh_v + it_v, d_tot[k][w + 1:]),
                wos.run_out_wos(c3_v, d_ch3[k][w + 1:]),
                s12_v, s3_v))

    return {"mps": mps_rows, "shipments": ship_rows, "inventory": inv_rows,
            "objective": val(prob.objective),
            "freight_cost": val(freight_cost),
            "total_short": total_short,
            "total_production": sum(r[3] for r in mps_rows)}


def run(db_path: str | Path, plan_id: str = "baseline",
        extra_prod_caps=None, time_limit: int = 600) -> dict:
    """Solve, persist (plan-scoped — other stored plans survive), validate."""
    from . import validate
    conn = db.connect(db_path)
    try:
        sol = solve(conn, plan_id, extra_prod_caps=extra_prod_caps,
                    time_limit=time_limit)
        conn.execute("BEGIN IMMEDIATE")
        try:
            db.init_mps_schema(conn)          # CREATE IF NOT EXISTS only
            for t in ("mps", "shipments", "inventory", "validation"):
                conn.execute(f"DELETE FROM {t} WHERE plan_id = ?", (plan_id,))
            conn.executemany("INSERT INTO mps VALUES (?,?,?,?,?)", sol["mps"])
            conn.executemany("INSERT INTO shipments VALUES (?,?,?,?,?,?,?)",
                             sol["shipments"])
            conn.executemany(
                "INSERT INTO inventory VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                sol["inventory"])
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        checks = validate.run_checks(conn, plan_id,
                                     extra_prod_caps=extra_prod_caps)
        failed = [c for c in checks if c[2] == "FAIL"]
        if failed:
            raise RuntimeError(f"constraint validation failed: {failed}")
        return {k: sol[k] for k in ("objective", "freight_cost",
                                    "total_short", "total_production")}
    finally:
        conn.close()
