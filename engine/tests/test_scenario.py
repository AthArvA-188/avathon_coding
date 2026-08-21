"""Phase 4 tests: the V2+V4 enclosure-shortage scenario on a reduced universe
— the shared weekly cap must bind, both plans must coexist, and the diff
summary must reconcile."""
import shutil

import pytest

from planz import db as planz_db
from planz import mps, params, scenario


@pytest.fixture(scope="module")
def scen_db(forecast_db, tmp_path_factory):
    _, db_path = forecast_db
    p = tmp_path_factory.mktemp("scenario") / "scen.db"
    shutil.copy(db_path, p)
    conn = planz_db.connect(p)
    conn.execute("DELETE FROM forecast WHERE variant NOT IN"
                 " ('Variant V1', 'Variant V2', 'Variant V4')")
    conn.close()
    base = mps.run(p, plan_id="baseline")
    info = scenario.run(p)
    return base, info, p


def test_shared_cap_binds(scen_db):
    _, info, p = scen_db
    conn = planz_db.connect(p)
    try:
        for w in range(params.SCENARIO_N_WEEKS):
            label = mps.week_label(w)
            combined = conn.execute(
                "SELECT COALESCE(SUM(production), 0) FROM mps"
                " WHERE plan_id = 'scenario' AND week_label = ?"
                " AND variant IN (?, ?)",
                (label, *params.SCENARIO_VARIANTS)).fetchone()[0]
            assert combined <= params.SCENARIO_WEEKLY_CAP + 0.5, (label, combined)
        # outside the window the cap must NOT bind artificially: at least one
        # later week exceeds it (catch-up production)
        beyond = conn.execute(
            "SELECT MAX(t) FROM (SELECT SUM(production) AS t FROM mps"
            " WHERE plan_id = 'scenario' AND variant IN (?, ?)"
            " AND week_label > ? GROUP BY week_label)",
            (*params.SCENARIO_VARIANTS,
             mps.week_label(params.SCENARIO_N_WEEKS - 1))).fetchone()[0]
        assert beyond > params.SCENARIO_WEEKLY_CAP
    finally:
        conn.close()


def test_both_plans_coexist_and_validate(scen_db):
    base, _, p = scen_db
    conn = planz_db.connect(p)
    try:
        plans = {r[0] for r in conn.execute("SELECT DISTINCT plan_id FROM mps")}
        assert {"baseline", "scenario"} <= plans
        # only the real plans; the copied DB may carry the deliberately-bad
        # synthetic plans from test_mps's validator tests
        fails = conn.execute("SELECT COUNT(*) FROM validation"
                             " WHERE status = 'FAIL' AND plan_id IN"
                             " ('baseline', 'scenario')").fetchone()[0]
        assert fails == 0
        # the scenario run's extra-cap check exists and passed
        extra = conn.execute("SELECT status FROM validation WHERE plan_id ="
                             " 'scenario' AND check_name = 'extra_cap_0'"
                             ).fetchone()
        assert extra is not None and extra[0] == "PASS"
        # baseline rows survived the scenario run untouched (plan-scoped writes)
        b_total = conn.execute("SELECT SUM(production) FROM mps"
                               " WHERE plan_id = 'baseline'").fetchone()[0]
        assert b_total == pytest.approx(base["total_production"], abs=0.5)
    finally:
        conn.close()


def test_diff_summary_reconciles(scen_db):
    base, info, p = scen_db
    assert len(info["allocation"]) == params.SCENARIO_N_WEEKS
    for a in info["allocation"]:
        assert a["combined_scen"] == pytest.approx(a["v2_scen"] + a["v4_scen"])
        assert a["combined_scen"] <= params.SCENARIO_WEEKLY_CAP + 0.5
    assert info["volume_delta"] == pytest.approx(
        info["scenario"]["production"] - info["baseline"]["production"])
    # the shortage cannot make the plan produce more overall
    assert info["volume_delta"] <= 0.5
    assert info["baseline"]["production"] == pytest.approx(
        base["total_production"], abs=0.5)
