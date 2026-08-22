"""Second-method tests: the greedy heuristic must satisfy every hard
constraint (same independent validators as the MILP) and the comparison
between the two methods must be well-formed."""
import shutil

import pytest

from planz import db as planz_db
from planz import heuristic, mps


@pytest.fixture(scope="module")
def two_method_db(forecast_db, tmp_path_factory):
    _, db_path = forecast_db
    p = tmp_path_factory.mktemp("heuristic") / "two.db"
    shutil.copy(db_path, p)
    conn = planz_db.connect(p)
    conn.execute("DELETE FROM forecast WHERE variant NOT IN"
                 " ('Variant V1', 'Variant V5', 'Variant V9')")
    conn.close()
    milp = mps.run(p, plan_id="baseline")
    greedy = heuristic.run(p)          # raises if any validator fails
    return milp, greedy, p


def test_heuristic_respects_hard_constraints(two_method_db):
    _, _, p = two_method_db
    conn = planz_db.connect(p)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM validation WHERE plan_id = 'heuristic'"
            " AND status = 'FAIL'").fetchone()[0] == 0
        # direct re-checks, independent of the validator module
        wk = conn.execute(
            "SELECT MAX(t) FROM (SELECT SUM(production) AS t FROM mps"
            " WHERE plan_id = 'heuristic' GROUP BY week_label)").fetchone()[0]
        assert wk <= 17_280.5
        slots = conn.execute(
            "SELECT MAX(t) FROM (SELECT SUM(packout) AS t FROM mps"
            " WHERE plan_id = 'heuristic' GROUP BY week_label)").fetchone()[0]
        assert slots <= 4
        v5 = conn.execute(
            "SELECT SUM(production) FROM mps WHERE plan_id = 'heuristic'"
            " AND variant = 'Variant V5'").fetchone()[0]
        assert v5 <= (38_000 - 35_516) + 0.5
    finally:
        conn.close()


def test_methods_coexist_and_compare(two_method_db):
    milp, greedy, p = two_method_db
    rows = heuristic.compare(p)
    assert [r[0] for r in rows] == ["baseline", "heuristic"]
    by_plan = {r[0]: r for r in rows}
    assert by_plan["baseline"][1] == pytest.approx(milp["total_production"], abs=1)
    assert by_plan["heuristic"][1] == pytest.approx(greedy["total_production"], abs=1)
    # greedy never serves demand the optimizer couldn't: its unmet demand
    # must be >= the MILP's (equality allowed on easy universes)
    assert by_plan["heuristic"][3] >= by_plan["baseline"][3] - 1


def test_heuristic_scenario_hook(two_method_db):
    _, _, p = two_method_db
    caps = [(("Variant V1",), range(3), 1000.0)]
    heuristic.run(p, plan_id="heuristic_scen", extra_prod_caps=caps)
    conn = planz_db.connect(p)
    try:
        worst = conn.execute(
            "SELECT MAX(production) FROM mps WHERE plan_id = 'heuristic_scen'"
            " AND variant = 'Variant V1' AND week_label <= ?",
            (mps.week_label(2),)).fetchone()[0]
        assert worst <= 1000.5
    finally:
        conn.close()
