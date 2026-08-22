"""Agentic loop tests on a reduced universe: the human gate holds, the
verifier gates proposals (hard constraints + service policy), the accepted
plan honors every signal-derived constraint, and the trail is auditable."""
import shutil

import pytest

from planz import agents, mps
from planz import db as planz_db


@pytest.fixture(autouse=True)
def force_rules_backend(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture(scope="module")
def loop_db(forecast_db, tmp_path_factory):
    _, db_path = forecast_db
    p = tmp_path_factory.mktemp("agents") / "loop.db"
    shutil.copy(db_path, p)
    conn = planz_db.connect(p)
    conn.execute("DELETE FROM forecast WHERE variant NOT IN"
                 " ('Variant V1', 'Variant V2', 'Variant V3', 'Variant V4')")
    planz_db.init_mps_schema(conn)      # empty plan tables for assertions
    conn.close()
    return p


def test_human_gate_blocks_without_approval(loop_db):
    out = agents.run_loop(loop_db, auto_approve=False)
    assert out["status"] == "needs_human"
    conn = planz_db.connect(loop_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM signals WHERE"
                            " status = 'approved'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM mps WHERE"
                            " plan_id = 'agentic'").fetchone()[0] == 0
    finally:
        conn.close()


@pytest.fixture(scope="module")
def loop_result(loop_db):
    return agents.run_loop(loop_db, time_limit=300, auto_approve=True), loop_db


def test_loop_accepts_a_valid_plan(loop_result):
    out, p = loop_result
    assert out["status"] == "accepted"
    assert out["method"] in ("greedy", "milp")
    conn = planz_db.connect(p)
    try:
        # accepted plan exists and all validator rows PASS
        assert conn.execute("SELECT COUNT(*) FROM mps WHERE"
                            " plan_id = 'agentic'").fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM validation WHERE plan_id ="
                            " 'agentic' AND status = 'FAIL'").fetchone()[0] == 0
        # signal-derived constraints hold on the persisted plan:
        for w in range(6):                       # V2+V4 supply cap
            label = mps.week_label(w)
            combined = conn.execute(
                "SELECT COALESCE(SUM(production), 0) FROM mps WHERE plan_id ="
                " 'agentic' AND week_label = ? AND variant IN"
                " ('Variant V2', 'Variant V4')", (label,)).fetchone()[0]
            assert combined <= 4500.5, (label, combined)
        blocked = conn.execute(                  # fast-boat suspension
            "SELECT COUNT(*) FROM shipments WHERE plan_id = 'agentic'"
            " AND geo = 'Geo G1' AND mode = 'Fast Boat Ocean'"
            " AND week_label BETWEEN ? AND ?",
            (mps.week_label(4), mps.week_label(7))).fetchone()[0]
        assert blocked == 0
    finally:
        conn.close()


def test_agent_log_is_a_complete_trail(loop_result):
    out, p = loop_result
    conn = planz_db.connect(p)
    try:
        rows = conn.execute("SELECT agent, action, outcome FROM agent_log"
                            " ORDER BY id").fetchall()
    finally:
        conn.close()
    agents_seen = [r["agent"] for r in rows]
    for required in ("ForecastAgent", "SignalAgent", "HumanGate",
                     "PlannerAgent", "VerifierAgent", "Orchestrator"):
        assert required in agents_seen, required
    # the verifier issued exactly one accept; the orchestrator closed it out
    assert rows[-1]["agent"] == "Orchestrator"
    assert rows[-1]["outcome"] == "DONE"
    accepts = [r for r in rows if r["outcome"] == "ACCEPTED"]
    assert len(accepts) == 1


def test_verifier_rejects_bad_planner(loop_db, monkeypatch):
    """Force the rejection path: a planner that proposes doing nothing must
    be rejected, and with every method bounced the loop escalates to a
    human instead of publishing anything."""
    from planz import heuristic

    real_solve = heuristic.solve                 # captured BEFORE patching

    def do_nothing(conn, plan_id, **kw):
        kw.pop("time_limit", None)
        sol = real_solve(conn, plan_id, **kw)    # real state, gutted plan
        sol["mps"] = [(p, v, w, 0.0, 0) for (p, v, w, _, _) in sol["mps"]]
        sol["shipments"] = []
        sol["total_production"] = 0.0
        sol["total_short"] = 10 ** 6             # nothing served
        return sol

    monkeypatch.setattr(heuristic, "solve", do_nothing)
    monkeypatch.setattr(mps, "solve", do_nothing)

    before = planz_db.connect(loop_db).execute(
        "SELECT COALESCE(SUM(production), 0) FROM mps WHERE"
        " plan_id = 'agentic'").fetchone()[0]
    out = agents.run_loop(loop_db, auto_approve=True)
    assert out["status"] == "needs_human"
    rejected = [t for t in out["trace"] if "REJECTED" in t]
    assert len(rejected) == 2                    # both methods bounced
    conn = planz_db.connect(loop_db)
    try:
        # the previously PUBLISHED plan survives a failed re-run untouched
        after = conn.execute("SELECT COALESCE(SUM(production), 0) FROM mps"
                             " WHERE plan_id = 'agentic'").fetchone()[0]
        assert after == pytest.approx(before) and after > 0
        # and no stale candidate is left behind
        assert conn.execute("SELECT COUNT(*) FROM mps WHERE plan_id ="
                            " 'agentic_candidate'").fetchone()[0] == 0
    finally:
        conn.close()


def test_service_policy_rejection_branch(loop_db):
    """An impossible tolerance forces the SERVICE branch (not hard fails):
    real solves, both rejected on policy, loop escalates to a human."""
    out = agents.run_loop(loop_db, auto_approve=True, service_tolerance=-1.0,
                          time_limit=300)
    assert out["status"] == "needs_human"
    policy_rejects = [t for t in out["trace"]
                      if "REJECTED" in t and "policy" in t]
    assert len(policy_rejects) == 2