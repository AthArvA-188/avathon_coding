"""Quantile-driven planning (docs D33): the demand cube can be built from
P10/P50/P90, the column name is whitelisted, and the default stays P50 so
every existing caller (scenario, agents, tests) is untouched."""
import numpy as np
import pytest

from planz import db as planz_db
from planz import mps


@pytest.fixture(scope="module")
def qconn(forecast_db):
    _, db_path = forecast_db
    conn = planz_db.connect(db_path)
    yield conn
    conn.close()


def test_load_demand_rejects_unknown_quantile(qconn):
    # the quantile is interpolated into SQL — the whitelist is the guard
    for bad in ("p37", "p50; DROP TABLE forecast", "P90", ""):
        with pytest.raises(ValueError):
            mps.load_demand(qconn, quantile=bad)


def test_quantile_cubes_are_ordered(qconn):
    """P10 <= P50 <= P90 must survive the cube build (split, aggregation,
    seasonal extension) — the forecast rows are sorted per-row at predict
    time, so any inversion here is a loader bug."""
    totals = {}
    for q in mps.QUANTILE_COLS:
        pairs, d_dir, d_ch3 = mps.load_demand(qconn, quantile=q)
        totals[q] = sum(float((d_dir[k][: mps.H] + d_ch3[k][: mps.H]).sum())
                        for k in pairs)
    assert totals["p10"] <= totals["p50"] <= totals["p90"]
    assert totals["p90"] > totals["p50"]      # the band is not degenerate
    assert totals["p10"] < totals["p50"]


def test_default_quantile_is_p50(qconn):
    pairs_d, dir_d, ch3_d = mps.load_demand(qconn)
    pairs_q, dir_q, ch3_q = mps.load_demand(qconn, quantile="p50")
    assert pairs_d == pairs_q
    for k in pairs_d:
        assert np.array_equal(dir_d[k], dir_q[k])
        assert np.array_equal(ch3_d[k], ch3_q[k])


def test_p90_cube_reconciles_with_sql(qconn):
    """Same reconciliation the P50 loader test does, at P90: the channel
    split must match straight SQL sums over the p90 column."""
    pairs, d_dir, d_ch3 = mps.load_demand(qconn, quantile="p90")
    ch3_total = sum(d_ch3[k][: mps.H].sum() for k in pairs)
    dir_total = sum(d_dir[k][: mps.H].sum() for k in pairs)
    sql_ch3 = qconn.execute("SELECT SUM(p90) FROM forecast"
                            " WHERE channel = 'Channel 3'").fetchone()[0]
    sql_dir = qconn.execute("SELECT SUM(p90) FROM forecast"
                            " WHERE channel <> 'Channel 3'").fetchone()[0]
    assert ch3_total == pytest.approx(sql_ch3, rel=1e-9)
    assert dir_total == pytest.approx(sql_dir, rel=1e-9)
