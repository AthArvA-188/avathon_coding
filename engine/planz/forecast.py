"""Demand forecast: XGBoost quantile models (P10/P50/P90) with recursive
multi-step prediction, scored on a 13-week holdout against naive and
seasonal-naive baselines, then refit on full history for the 52-week horizon.
NPI analog ramps, EOL zeros and volume caps come from lifecycle.py.

Writes the `forecast` and `forecast_scores` tables.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
from xgboost import XGBRegressor

from . import db, lifecycle, metrics, params
from . import features as ft

QUANTILES = (0.1, 0.5, 0.9)
HOLDOUT_START_O = 91               # 2023W27 (params.HOLDOUT_START)
LAST_O = 103                       # 2023W39
H_START, H_END = 104, 155          # horizon

XGB_PARAMS = dict(
    n_estimators=600, learning_rate=0.05, max_depth=6, min_child_weight=5.0,
    subsample=0.9, colsample_bytree=0.9, reg_lambda=1.0,
    tree_method="hist", random_state=42, n_jobs=-1,
)


def train_models(X: np.ndarray, y: np.ndarray) -> dict[float, XGBRegressor]:
    """Quantile models trained on log1p(units): a global model across series
    whose scales span 4 orders of magnitude needs a variance-stabilizing
    transform, and quantiles are invariant under monotone transforms, so
    expm1(predicted log-quantile) is exactly the unit-space quantile.

    Rows are weighted by log1p(volume)+1 so the pinball loss cares more
    about high-volume weeks; on this data that cut holdout WAPE 41%->38%
    and bias -30%->+3% (experiment log in docs/decisions.md D9)."""
    weight = np.log1p(y) + 1.0
    models = {}
    for q in QUANTILES:
        m = XGBRegressor(objective="reg:quantileerror", quantile_alpha=q,
                         **XGB_PARAMS)
        m.fit(X, np.log1p(y), sample_weight=weight)
        models[q] = m
    return models


def recursive_predict(fb: ft.FeatureBuilder, models: dict[float, XGBRegressor],
                      start_o: int, end_o: int) -> dict[tuple, dict[float, np.ndarray]]:
    """Week-by-week prediction; each week's P50 is appended to the series
    history so later weeks' lag features see it. Quantiles are clipped at 0
    and sorted so p10 <= p50 <= p90 row-wise."""
    keys = list(fb.history)
    hists = {k: fb.history[k][:start_o].copy() for k in keys}
    n = end_o - start_o + 1
    preds = {k: {q: np.zeros(n) for q in QUANTILES} for k in keys}
    for i, o in enumerate(range(start_o, end_o + 1)):
        X = np.array([fb.make_row(k, o, hists[k]) for k in keys], dtype=float)
        raw = np.expm1(np.vstack([models[q].predict(X) for q in QUANTILES]))
        ordered = np.sort(np.clip(raw, 0.0, None), axis=0)
        for j, k in enumerate(keys):
            for qi, q in enumerate(QUANTILES):
                preds[k][q][i] = ordered[qi, j]
            hists[k] = np.append(hists[k], ordered[1, j])
    return preds


def backtest(fb: ft.FeatureBuilder) -> list[tuple]:
    """Train through 2023W26, recursively predict the 13-week holdout, score
    XGB P50 vs naive (last value) and seasonal-naive (same fiscal week last
    year). Returns forecast_scores rows."""
    X, y = fb.training_data(HOLDOUT_START_O - 1)
    models = train_models(X, y)
    preds = recursive_predict(fb, models, HOLDOUT_START_O, LAST_O)

    n = LAST_O - HOLDOUT_START_O + 1
    keys = list(fb.history)
    actual = {k: fb.history[k][HOLDOUT_START_O:LAST_O + 1] for k in keys}
    point = {
        "xgb": {k: preds[k][0.5] for k in keys},
        "naive": {k: np.full(n, fb.history[k][HOLDOUT_START_O - 1])
                  for k in keys},
        "seasonal_naive": {
            k: np.array([fb.history[k][ft.yoy_offset(o)]
                         for o in range(HOLDOUT_START_O, LAST_O + 1)])
            for k in keys},
    }

    scopes = [("overall", "overall", keys)]
    for geo in sorted({k[1] for k in keys}):
        scopes.append(("geo", geo, [k for k in keys if k[1] == geo]))
    for variant in sorted({k[0] for k in keys}):
        scopes.append(("variant", variant, [k for k in keys if k[0] == variant]))

    rows = []
    for model, series in point.items():
        for scope_type, scope, sub in scopes:
            a = np.concatenate([actual[k] for k in sub])
            f = np.concatenate([series[k] for k in sub])
            pb10 = pb90 = None
            if model == "xgb":
                lo = np.concatenate([preds[k][0.1] for k in sub])
                hi = np.concatenate([preds[k][0.9] for k in sub])
                pb10 = metrics.pinball(a, lo, 0.1)
                pb90 = metrics.pinball(a, hi, 0.9)
            rows.append((model, scope_type, scope,
                         metrics.wape(a, f), metrics.smape(a, f),
                         metrics.bias(a, f), pb10, pb90))
    return rows


def production(conn: sqlite3.Connection, fb: ft.FeatureBuilder) -> list[tuple]:
    """Refit on all 104 actual weeks, predict the 52-week horizon, add NPI
    ramps and EOL zeros, enforce volume caps. Returns forecast rows."""
    X, y = fb.training_data(LAST_O)
    models = train_models(X, y)
    preds = recursive_predict(fb, models, H_START, H_END)

    fc = {k: {"p10": preds[k][0.1], "p50": preds[k][0.5],
              "p90": preds[k][0.9]} for k in preds}
    method = {k: "xgb" for k in fc}
    for k, v in lifecycle.npi_forecasts(conn, fb).items():
        fc[k] = v
        method[k] = "npi_ramp"
    zeros = np.zeros(H_END - H_START + 1)
    for k in fb.all_history:
        if k[0] == "Variant V12":
            fc[k] = {"p10": zeros.copy(), "p50": zeros.copy(),
                     "p90": zeros.copy()}
            method[k] = "eol_zero"

    lifecycle.apply_caps(fc, lifecycle.cap_specs(conn))

    rows = []
    for k, arrs in fc.items():
        variant, geo, channel = k
        for i in range(H_END - H_START + 1):
            rows.append((variant, geo, channel, ft.label_of(H_START + i),
                         float(arrs["p10"][i]), float(arrs["p50"][i]),
                         float(arrs["p90"][i]), method[k]))
    return rows


def run(db_path: str | Path) -> dict:
    conn = db.connect(db_path)
    try:
        fb = ft.FeatureBuilder(conn)
        score_rows = backtest(fb)
        fc_rows = production(conn, fb)
        conn.execute("BEGIN IMMEDIATE")
        try:
            db.init_forecast_schema(conn)
            conn.executemany(
                "INSERT INTO forecast VALUES (?,?,?,?,?,?,?,?)", fc_rows)
            conn.executemany(
                "INSERT INTO forecast_scores VALUES (?,?,?,?,?,?,?,?)",
                score_rows)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        headline = {r[0]: round(r[3], 4) for r in score_rows
                    if r[2] == "overall"}
        return {"forecast_rows": len(fc_rows), "series": len(fc_rows) // 52,
                "holdout_wape": headline}
    finally:
        conn.close()
