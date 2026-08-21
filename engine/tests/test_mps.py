"""Phase 3 tests: demand cube, freight policy, production caps, and — most
important — the independent constraint validators, proven against synthetic
plans that violate each hard constraint in turn."""
import numpy as np
import pytest

from planz import db as planz_db
from planz import mps, validate


@pytest.fixture(scope="module")
def mconn(forecast_db):
    """Connection to the temp DB (forecast tables present) with MPS schema."""
    _, db_path = forecast_db
    conn = planz_db.connect(db_path)
    conn.execute("BEGIN")
    planz_db.init_mps_schema(conn)
    conn.execute("COMMIT")
    yield conn
    conn.close()


# ---------- loaders & policy ----------

def test_load_demand_split_and_extension(mconn):
    pairs, d_dir, d_ch3 = mps.load_demand(mconn)
    assert len(pairs) > 20
    # the channel SPLIT must reconcile independently, not just the total —
    # a swapped channel routing would break the two-tier inventory model
    ch3_total = sum(d_ch3[k][:mps.H].sum() for k in pairs)
    dir_total = sum(d_dir[k][:mps.H].sum() for k in pairs)
    sql_ch3 = mconn.execute("SELECT SUM(p50) FROM forecast"
                            " WHERE channel = 'Channel 3'").fetchone()[0]
    sql_dir = mconn.execute("SELECT SUM(p50) FROM forecast"
                            " WHERE channel <> 'Channel 3'").fetchone()[0]
    assert ch3_total == pytest.approx(sql_ch3, rel=1e-9)
    assert dir_total == pytest.approx(sql_dir, rel=1e-9)
    for k in pairs:                       # seasonal extension repeats year-1
        assert np.allclose(d_dir[k][mps.H:], d_dir[k][:mps.EXT])
        assert np.allclose(d_ch3[k][mps.H:], d_ch3[k][:mps.EXT])
        assert len(d_dir[k]) == mps.H + mps.EXT


def test_freight_modes_policy(mconn):
    m = mps.freight_modes(mconn)
    # cost-Pareto frontier per geo, cheapest first (docs D12)
    assert m["Geo G1"] == [("Standard Ocean", 8, 2.0),
                          ("Fast Boat Ocean", 5, 3.5), ("Air", 1, 7.0)]
    assert m["Geo G2"] == [("Standard Ocean", 11, 2.5), ("Air", 1, 7.0)]
    assert m["Geo G4"] == [("Ground", 1, 2.5)]            # Air dominated
    assert m["Geo G3"] == [("Air", 1, 7.0)]               # Air-only geos
    assert m["Geo G5"] == [("Air", 1, 7.0)]


def test_production_caps(mconn):
    pairs, d_dir, d_ch3 = mps.load_demand(mconn)
    d_tot = {k: d_dir[k] + d_ch3[k] for k in pairs}
    caps = mps.production_caps(mconn, d_tot)
    assert "Variant V1" not in caps                       # core: uncapped
    assert caps["Variant V5"] == pytest.approx(38_000 - 35_516)
    assert caps["Variant V10"] == pytest.approx(57_407)
    # V8: G1 forward volume plus its (uncapped) G2 horizon demand,
    # recomputed independently via SQL, not through load_demand
    v8_g2 = mconn.execute(
        "SELECT SUM(p50) FROM forecast WHERE variant = 'Variant V8'"
        " AND geo = 'Geo G2'").fetchone()[0]
    assert v8_g2 > 0
    assert caps["Variant V8"] == pytest.approx(13_832 + v8_g2)


# ---------- validators vs synthetic violating plans ----------

def _insert_plan(conn, plan_id, rows):
    conn.execute("DELETE FROM mps WHERE plan_id = ?", (plan_id,))
    conn.executemany("INSERT INTO mps VALUES (?,?,?,?,?)",
                     [(plan_id, *r) for r in rows])


def test_validators_pass_on_clean_plan(mconn):
    # a modest, fully consistent plan: one variant, one week, shipped exactly
    wk = mps.week_label(0)
    _insert_plan(mconn, "t_ok", [("Variant V1", wk, 1000.0, 1)])
    mconn.execute("DELETE FROM shipments WHERE plan_id = 't_ok'")
    mconn.execute("INSERT INTO shipments VALUES ('t_ok','Variant V1','Geo G1',"
                  "?, 'Standard Ocean', 1000.0, 2000.0)", (wk,))
    mconn.execute("DELETE FROM inventory WHERE plan_id = 't_ok'")
    checks = validate.run_checks(mconn, "t_ok")
    assert all(c[2] == "PASS" for c in checks), checks


def test_validators_catch_each_violation(mconn):
    wk0, wk1 = mps.week_label(0), mps.week_label(1)
    rows = []
    # weekly cap + slots: 5 variants packed, 20k units in week 0
    for v in ["Variant V1", "Variant V2", "Variant V3",
              "Variant V4", "Variant V6"]:
        rows.append((v, wk0, 4000.0, 1))
    # linkage: production without a slot
    rows.append(("Variant V9", wk1, 500.0, 0))
    # volume cap: V5 far beyond its remaining volume; also pushes the
    # quarter total (320,500) past the 224,000 quarterly cap
    rows.append(("Variant V5", wk1, 300000.0, 1))
    _insert_plan(mconn, "t_bad", rows)
    mconn.execute("DELETE FROM shipments WHERE plan_id = 't_bad'")
    mconn.execute("DELETE FROM inventory WHERE plan_id = 't_bad'")
    mconn.execute("INSERT INTO inventory VALUES ('t_bad','Variant V1','Geo G1',"
                  "?, -10.0, 0, 0, NULL, NULL, 0, 0)", (wk0,))

    result = {c[1]: c[2] for c in validate.run_checks(
        mconn, "t_bad",
        extra_prod_caps=[(("Variant V1", "Variant V2"), range(0, 2), 4500.0)])}
    assert result["weekly_capacity"] == "FAIL"        # 300,000 > 17,280
    assert result["quarterly_capacity"] == "FAIL"
    assert result["packout_slots"] == "FAIL"          # 5 > 4
    assert result["packout_linkage"] == "FAIL"
    assert result["ship_conservation"] == "FAIL"      # no shipments at all
    assert result["nonnegative_inventory"] == "FAIL"
    assert result["volume_caps"] == "FAIL"
    assert result["extra_cap_0"] == "FAIL"            # V1+V2 8,000 > 4,500


def test_validation_rows_persisted(mconn):
    rows = mconn.execute(
        "SELECT status FROM validation WHERE plan_id = 't_bad'").fetchall()
    assert rows and any(r[0] == "FAIL" for r in rows)


# ---------- end-to-end MILP smoke solve ----------
# The runtime validators check hard constraints only — an all-zero plan
# passes them — so objective/soft-goal regressions (a dropped shortage
# penalty, flipped WOS targets) are only catchable by actually solving.

@pytest.fixture(scope="module")
def smoke_db(forecast_db, tmp_path_factory):
    import shutil
    _, db_path = forecast_db
    p = tmp_path_factory.mktemp("mps_smoke") / "smoke.db"
    shutil.copy(db_path, p)
    conn = planz_db.connect(p)
    conn.execute("DELETE FROM forecast WHERE variant NOT IN"
                 " ('Variant V1', 'Variant V5', 'Variant V9')")
    conn.close()
    info = mps.run(p, plan_id="smoke")
    return info, p


def test_mps_smoke_solve(smoke_db):
    info, p = smoke_db
    conn = planz_db.connect(p)
    try:
        # optimal, validated (run() raises otherwise), and demand is served
        assert info["total_short"] == pytest.approx(0, abs=5)
        demand = conn.execute("SELECT SUM(p50) FROM forecast").fetchone()[0]
        assert info["total_production"] > 0.5 * demand   # not a do-nothing plan
        # V5's volume cap binds production, not just the forecast
        v5 = conn.execute("SELECT SUM(production) FROM mps WHERE"
                          " plan_id = 'smoke' AND variant = 'Variant V5'"
                          ).fetchone()[0]
        assert v5 <= (38_000 - 35_516) + 0.5
        # only declared freight modes are used
        used = {r[0] for r in conn.execute(
            "SELECT DISTINCT mode FROM shipments WHERE plan_id = 'smoke'")}
        assert used <= {"Standard Ocean", "Fast Boat Ocean", "Air", "Ground"}
        assert conn.execute("SELECT COUNT(*) FROM validation WHERE"
                            " plan_id = 'smoke' AND status = 'FAIL'"
                            ).fetchone()[0] == 0
    finally:
        conn.close()


def test_mps_run_raises_on_validation_failure(smoke_db, monkeypatch):
    _, p = smoke_db
    monkeypatch.setattr(validate, "run_checks",
                        lambda *a, **k: [("x", "forced", "FAIL", "forced")])
    with pytest.raises(RuntimeError, match="validation failed"):
        mps.run(p, plan_id="smoke_fail")
