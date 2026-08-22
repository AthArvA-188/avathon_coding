"""Agentic planning loop prototype (docs D28, brief §3.4).

The pipeline's modules, given explicit roles, bounded authority, and a real
rejection/repair loop:

  ForecastAgent   asserts the demand precondition (never retrains mid-loop).
  SignalAgent     extracts typed events; proposes only — it cannot approve.
  HumanGate       CLOSED by default. Auto-approval happens only when the
                  caller explicitly requests it (--auto-approve), and even
                  then a demand-delta guard forces human sign-off when the
                  extracted shocks move aggregate demand by more than 15%.
  PlannerAgent    proposes under the approved constraints: greedy first,
                  escalate to the MILP on rejection. Never self-certifies.
  VerifierAgent   re-checks hard constraints from the persisted candidate
                  (validate.py) and a service policy computed from the
                  candidate's own inventory rows — never from the planner's
                  self-reported numbers.
  Orchestrator    stages every candidate under 'agentic_candidate' and
                  promotes to 'agentic' only on acceptance, so a failed
                  re-run can never destroy the previously published plan.
                  agent_log is append-only: the audit trail spans runs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import db, heuristic, mps, signals, validate

SERVICE_TOLERANCE = 0.005      # unmet demand <= 0.5% of demand
DELTA_GUARD = 0.15             # |shock delta| above this share => human only
PLAN_ID = "agentic"
CANDIDATE = "agentic_candidate"


def _log(conn, agent: str, action: str, detail: str, outcome: str):
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO agent_log (ts, agent, action, detail, outcome)"
            " VALUES (?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"),
             agent, action, detail, outcome))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _promote(conn, candidate: str, final: str):
    conn.execute("BEGIN IMMEDIATE")
    try:
        for t in ("mps", "shipments", "inventory", "validation"):
            conn.execute(f"DELETE FROM {t} WHERE plan_id = ?", (final,))
            conn.execute(f"UPDATE {t} SET plan_id = ? WHERE plan_id = ?",
                         (final, candidate))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _exact_shock_delta(conn, demand_mults) -> float:
    """Exact demand moved by the shocks: sum over shocks of (mult-1) x the
    forecast P50 inside the shocked weeks/geo/variant (no seasonal proxy)."""
    delta = 0.0
    for v, g, ws, mult in demand_mults:
        labels = [mps.week_label(w) for w in ws]
        ph = ",".join("?" for _ in labels)
        sql = (f"SELECT COALESCE(SUM(p50), 0) FROM forecast WHERE variant = ?"
               f" AND week_label IN ({ph})")
        args = [v, *labels]
        if g:
            sql += " AND geo = ?"
            args.append(g)
        delta += (mult - 1) * conn.execute(sql, args).fetchone()[0]
    return delta


def run_loop(db_path: str | Path, inbox_dir=None, auto_approve: bool = False,
             service_tolerance: float = SERVICE_TOLERANCE,
             time_limit: int = 600) -> dict:
    conn = db.connect(db_path)
    trace: list[str] = []

    def step(agent, action, detail, outcome):
        _log(conn, agent, action, detail, outcome)
        trace.append(f"{agent:>13} | {action:<18} | {detail} -> {outcome}")

    try:
        db.init_signals_schema(conn)
        step("Orchestrator", "run-start",
             f"auto_approve={auto_approve}", "BEGIN")

        # -- ForecastAgent: precondition, not retraining -------------------
        n_fc = conn.execute("SELECT COUNT(*) FROM forecast").fetchone()[0]
        if n_fc == 0:
            step("ForecastAgent", "precondition", "forecast table empty",
                 "ABORT: run --forecast first")
            return {"status": "aborted", "trace": trace}
        demand_total = conn.execute(
            "SELECT SUM(p50) FROM forecast").fetchone()[0]
        step("ForecastAgent", "precondition",
             f"{n_fc:,} forecast rows, {demand_total:,.0f} u demand", "OK")

        # -- SignalAgent: propose, never apply -----------------------------
        found = signals.extract_inbox(db_path, inbox_dir)
        step("SignalAgent", "extract",
             f"{len(found)} events (statuses of prior human decisions"
             " preserved)", "pending")

        # -- HumanGate ------------------------------------------------------
        if auto_approve:
            n_app = signals.approve(db_path)
            left = signals.pending_count(conn)
            step("HumanGate", "auto-approve",
                 f"{n_app} events approved on explicit request;"
                 f" {left} below-floor left pending", "approved")
        approved = signals.load_approved(conn)
        if not approved:
            left = signals.pending_count(conn)
            step("HumanGate", "hold",
                 f"no approved events ({left} pending) — approve with"
                 " --approve-signals or run with --auto-approve",
                 "needs_human")
            return {"status": "needs_human", "trace": trace}
        constraints = signals.compile_events(approved)
        step("SignalAgent", "compile",
             f"{len(constraints['extra_prod_caps'])} caps,"
             f" {len(constraints['demand_mults'])} demand shocks,"
             f" {len(constraints['mode_blocks'])} freight blocks", "OK")

        # demand-delta guard: big shocks are a human conversation
        delta = _exact_shock_delta(conn, constraints["demand_mults"])
        if abs(delta) > DELTA_GUARD * demand_total:
            step("VerifierAgent", "delta-guard",
                 f"shocks move demand by {delta:+,.0f} u"
                 f" (>{DELTA_GUARD:.0%} of forecast)", "needs_human")
            return {"status": "needs_human", "trace": trace}
        shocked_total = demand_total + delta
        tolerance_units = service_tolerance * max(demand_total, shocked_total)

        # -- PlannerAgent proposes; VerifierAgent gates ---------------------
        mps.drop_plan(conn, CANDIDATE)          # clear any stale candidate
        methods = [("greedy", lambda: heuristic.solve(
                        conn, CANDIDATE, **constraints)),
                   ("milp", lambda: mps.solve(
                        conn, CANDIDATE, time_limit=time_limit,
                        **constraints))]
        accepted = None
        result = {}
        for name, propose in methods:
            step("PlannerAgent", "propose", f"method={name}", "candidate")
            try:
                sol = propose()
                mps.persist_plan(conn, CANDIDATE, sol)
                checks = validate.run_checks(
                    conn, CANDIDATE,
                    extra_prod_caps=constraints["extra_prod_caps"],
                    mode_blocks=constraints["mode_blocks"],
                    demand_mults=constraints["demand_mults"])
            except Exception as exc:            # a crashed proposal is a
                step("PlannerAgent", "error",   # rejection, not a loop death
                     f"{name}: {type(exc).__name__}: {exc}", "FAILED")
                mps.drop_plan(conn, CANDIDATE)
                continue
            hard_fails = [c[1] for c in checks if c[2] == "FAIL"]
            # service policy from the PERSISTED candidate, not self-report
            short = conn.execute(
                "SELECT COALESCE(SUM(short_direct + short_ch3), 0)"
                " FROM inventory WHERE plan_id = ?", (CANDIDATE,)
                ).fetchone()[0]
            if hard_fails:
                step("VerifierAgent", "reject",
                     f"{name}: hard constraints {hard_fails}", "REJECTED")
                mps.drop_plan(conn, CANDIDATE)
                continue
            if short > tolerance_units:
                step("VerifierAgent", "reject",
                     f"{name}: unmet {short:,.0f} u > policy"
                     f" {tolerance_units:,.0f} u", "REJECTED")
                mps.drop_plan(conn, CANDIDATE)
                continue
            step("VerifierAgent", "accept",
                 f"{name}: {len(checks)} checks PASS, unmet {short:,.0f} u"
                 " within policy", "ACCEPTED")
            accepted = name
            result = {"freight_cost": sol["freight_cost"],
                      "total_short": short,
                      "total_production": sol["total_production"]}
            break

        if accepted is None:
            step("Orchestrator", "escalate",
                 "no method satisfies policy; previously published plan"
                 " (if any) left untouched", "needs_human")
            return {"status": "needs_human", "trace": trace}

        # -- Orchestrator: promote candidate, report vs baseline ------------
        _promote(conn, CANDIDATE, PLAN_ID)
        base = conn.execute(
            "SELECT SUM(production) FROM mps WHERE plan_id = 'baseline'"
            ).fetchone()[0]
        delta_p = (result["total_production"] - base) if base else None
        step("Orchestrator", "publish",
             f"plan '{PLAN_ID}' by {accepted};"
             f" production {result['total_production']:,.0f} u"
             + (f" ({delta_p:+,.0f} vs baseline)" if delta_p is not None else ""),
             "DONE")
        return {"status": "accepted", "method": accepted, **result,
                "trace": trace}
    finally:
        conn.close()
