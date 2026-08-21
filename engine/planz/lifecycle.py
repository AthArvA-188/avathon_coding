"""Variant lifecycle: NPI analog ramps for zero-history launches, EOL zeros,
and lifetime/forward volume cap enforcement (docs D10, D23).

Cap interpretation (D23, evidenced in docs/decisions.md):
- One-time deals (V5-V7, V12): the stated number is a LIFETIME total;
  remaining = total - net units already sold.
- Exclusives (V8-V11): the stated per-geo numbers are FORWARD volumes from
  the last actual week (V8 has already sold 2.4x its stated G1 number, so a
  lifetime reading is impossible). For the in-horizon launches V10/V11 the
  forward volume IS the whole deal.
- V10 has a stated Geo G2 volume but no G2 series in the data — that volume
  is reallocated across its existing rest-of-world geos (G3/G4/G5) by their
  core-variant demand mix. Client question.
"""
from __future__ import annotations

import sqlite3

import numpy as np

from . import features as ft

H_START, H_END = 104, 155          # horizon offsets (2023W40..2024W39)
H_N = H_END - H_START + 1
NPI_RELEASE_O = 113                # 2023W49, V10 and V11
NPI_BAND = 0.4                     # +-40% for P10/P90 (judgment, documented)

ANALOGS = [("Variant V8", "2023W02"), ("Variant V9", "2022W48")]


def analog_curve(fb: ft.FeatureBuilder, n_weeks: int,
                 seas: np.ndarray | None = None) -> np.ndarray:
    """Average normalized launch trajectory (share of volume by week-since-
    release) of the V8/V9 analogs in Geo G1, extended/truncated to n_weeks.

    Pass `seas` (the seasonal index over week offsets) to DESEASONALIZE each
    analog by its own calendar before averaging — otherwise the analogs'
    holiday spikes get double-counted when the ramp is later multiplied by
    the target window's seasonal index."""
    curves = []
    for variant, release in ANALOGS:
        ro = ft.offset_of(release)
        total = np.zeros(ft.N_ACTUAL - ro)
        for (v, g, c), hist in fb.all_history.items():
            if v == variant and g == "Geo G1":
                total += hist[ro:]
        if seas is not None:
            total = total / np.maximum(seas[ro:ro + len(total)], 0.25)
        if len(total) < n_weeks:                     # extend with recent rate
            tail = np.full(n_weeks - len(total), total[-4:].mean())
            total = np.concatenate([total, tail])
        curve = total[:n_weeks]
        curves.append(curve / curve.sum())
    return np.mean(curves, axis=0)


def seasonal_index(fb: ft.FeatureBuilder) -> np.ndarray:
    """Multiplicative holiday index per week offset for the horizon, from
    core-variant (V1-V4) Geo G1 sell-through: mean of the same-fiscal-week
    values in prior years / overall weekly mean."""
    core = np.zeros(ft.N_ACTUAL)
    for (v, g, c), hist in fb.all_history.items():
        if v in ("Variant V1", "Variant V2", "Variant V3", "Variant V4") \
                and g == "Geo G1":
            core += hist
    overall = core.mean()
    idx = np.ones(ft.N_WEEKS)
    for o in range(ft.N_WEEKS):
        vals = []
        prev = ft.yoy_offset(o)
        while prev is not None and prev < ft.N_ACTUAL:
            vals.append(core[prev])
            prev = ft.yoy_offset(prev)
        if vals:
            idx[o] = np.mean(vals) / overall
    return idx


def core_geo_mix(fb: ft.FeatureBuilder, geos: list[str]) -> dict[str, float]:
    tot = {g: 0.0 for g in geos}
    for (v, g, c), hist in fb.all_history.items():
        if v in ("Variant V1", "Variant V2", "Variant V3", "Variant V4") \
                and g in tot:
            tot[g] += hist.sum()
    s = sum(tot.values())
    return {g: (t / s if s else 1.0 / len(geos)) for g, t in tot.items()}


def npi_geo_volumes(conn: sqlite3.Connection,
                    fb: ft.FeatureBuilder) -> dict[tuple[str, str], float]:
    """(variant, geo) -> deal volume to ramp over the horizon."""
    out = {}
    caps = {r["variant"]: r for r in conn.execute(
        "SELECT * FROM variants WHERE variant IN"
        " ('Variant V10', 'Variant V11')")}
    v10 = caps["Variant V10"]
    out[("Variant V10", "Geo G1")] = v10["cap_g1"]
    # stated G2 volume has no G2 series -> spread across existing RoW geos
    row_geos = ["Geo G3", "Geo G4", "Geo G5"]
    mix = core_geo_mix(fb, row_geos)
    for g in row_geos:
        out[("Variant V10", g)] = v10["cap_g2"] * mix[g]
    v11 = caps["Variant V11"]
    out[("Variant V11", "Geo G1")] = v11["cap_g1"]
    out[("Variant V11", "Geo G2")] = v11["cap_g2"]
    out[("Variant V11", "Geo G4")] = v11["cap_g35"]
    return out


def npi_forecasts(conn: sqlite3.Connection, fb: ft.FeatureBuilder
                  ) -> dict[tuple, dict[str, np.ndarray]]:
    """(variant, geo, channel) -> {'p10','p50','p90'} arrays over the horizon.
    All volume goes to the Channel 3 series (the analogs sold ~100% Ch3);
    other existing channel grains get explicit zeros."""
    n_ramp = H_END - NPI_RELEASE_O + 1
    seas = seasonal_index(fb)
    shape = analog_curve(fb, n_ramp, seas) * seas[NPI_RELEASE_O:H_END + 1]
    shape = shape / shape.sum()
    volumes = npi_geo_volumes(conn, fb)

    out = {}
    for key in fb.all_history:
        variant, geo, channel = key
        if variant not in ("Variant V10", "Variant V11"):
            continue
        p50 = np.zeros(H_N)
        if channel == "Channel 3" and (variant, geo) in volumes:
            ramp = volumes[(variant, geo)] * shape
            p50[NPI_RELEASE_O - H_START:] = ramp
        out[key] = {"p10": p50 * (1 - NPI_BAND), "p50": p50,
                    "p90": p50 * (1 + NPI_BAND)}
    return out


def cap_specs(conn: sqlite3.Connection) -> list[tuple[str, tuple[str, ...], float]]:
    """(variant, geos-in-scope, remaining forward volume). Empty geos tuple
    means all geos. Zero-cap geos with active history are left uncapped
    (client question, docs D23)."""
    sold = {}
    for r in conn.execute(
            "SELECT s.variant, SUM(a.units) AS st FROM actuals a"
            " JOIN series s USING (series_id) WHERE a.metric = 'ST'"
            " GROUP BY s.variant"):
        sold[r["variant"]] = r["st"]

    specs = []
    for r in conn.execute("SELECT * FROM variants"):
        v = r["variant"]
        if r["classification"] in ("one_time_deal", "one_time_drop"):
            specs.append((v, (), max(0.0, r["cap_total"] - sold.get(v, 0.0))))
        elif r["classification"] == "exclusive":
            if v == "Variant V10":
                specs.append((v, ("Geo G1",), r["cap_g1"]))
                specs.append((v, ("Geo G3", "Geo G4", "Geo G5"), r["cap_g2"]))
            elif v == "Variant V11":
                specs.append((v, ("Geo G1",), r["cap_g1"]))
                specs.append((v, ("Geo G2",), r["cap_g2"]))
                specs.append((v, ("Geo G4",), r["cap_g35"]))
            else:                                    # V8, V9: forward volume
                specs.append((v, ("Geo G1",), r["cap_g1"]))
    return specs


def apply_caps(forecasts: dict[tuple, dict[str, np.ndarray]],
               specs: list[tuple[str, tuple[str, ...], float]]) -> None:
    """Clip horizon forecasts in place so cumulative P50 within each spec's
    scope never exceeds the remaining volume; once exhausted, later weeks are
    zero. P10/P90 are scaled by the same per-week factor."""
    for variant, geos, remaining in specs:
        keys = [k for k in forecasts
                if k[0] == variant and (not geos or k[1] in geos)]
        if not keys:
            continue
        cum = 0.0
        for i in range(H_N):
            week_total = sum(forecasts[k]["p50"][i] for k in keys)
            if week_total <= 0:
                continue
            factor = 1.0
            if cum + week_total > remaining:
                factor = max(0.0, (remaining - cum) / week_total)
            if factor < 1.0:
                for k in keys:
                    for q in ("p10", "p50", "p90"):
                        forecasts[k][q][i] *= factor
            cum += week_total * factor
