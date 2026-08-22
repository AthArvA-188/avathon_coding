"""Program Z planning pipeline CLI.

Usage (from repo root, inside the `avathon` conda env):
    python engine/run_pipeline.py --ingest
    python engine/run_pipeline.py --all
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from planz import ingest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Program Z planning pipeline")
    ap.add_argument("--xlsx", default=str(ROOT / "program_z.xlsx"))
    ap.add_argument("--db", default=str(ROOT / "planz.db"))
    ap.add_argument("--ingest", action="store_true", help="xlsx -> SQLite")
    ap.add_argument("--forecast", action="store_true", help="(phase 2)")
    ap.add_argument("--mps", action="store_true", help="(phase 3)")
    ap.add_argument("--scenario", action="store_true", help="(phase 4)")
    ap.add_argument("--heuristic", action="store_true",
                    help="second method: greedy plan + comparison vs MILP")
    ap.add_argument("--signals", action="store_true",
                    help="extract planning events from the unstructured inbox"
                         " and score the extractor vs labeled fixtures")
    ap.add_argument("--agents", action="store_true",
                    help="run the agentic planning loop (signals -> approval"
                         " -> greedy-first proposal -> verifier -> escalate)")
    ap.add_argument("--auto-approve", action="store_true",
                    help="explicitly allow the loop to auto-approve extracted"
                         " events above the confidence floor (demo mode)")
    ap.add_argument("--approve-signals", action="store_true",
                    help="HUMAN GATE: approve pending events >= 0.8 confidence"
                         " (image events sit below this floor by design)")
    ap.add_argument("--approve-signal", action="append", type=int,
                    metavar="ID",
                    help="HUMAN GATE: approve ONE pending event by row id"
                         " (repeatable) — required for image events, after"
                         " comparing the stored transcription with the image")
    ap.add_argument("--reject-signals", action="store_true",
                    help="HUMAN GATE: reject all pending events (survives"
                         " re-extraction)")
    ap.add_argument("--quantile", choices=["p10", "p50", "p90"],
                    default="p50",
                    help="forecast quantile that drives the --mps and"
                         " --heuristic demand cube (default p50). Non-p50"
                         " plans persist under their own plan_id (e.g."
                         " baseline_p90) next to the P50 plans; the V2+V4"
                         " scenario always re-solves P50 vs the P50 baseline")
    ap.add_argument("--all", action="store_true", help="run every stage")
    args = ap.parse_args(argv)
    q = args.quantile
    plan_mps = "baseline" if q == "p50" else f"baseline_{q}"
    plan_heur = "heuristic" if q == "p50" else f"heuristic_{q}"

    stages = {k: (getattr(args, k) or args.all)
              for k in ("ingest", "forecast", "mps", "scenario", "heuristic")}
    stages["signals"] = args.signals            # explicit-only prototypes
    stages["agents"] = args.agents
    if not (any(stages.values()) or args.approve_signals
            or args.approve_signal or args.reject_signals):
        ap.error("pick at least one stage (e.g. --ingest or --all)")

    if stages["ingest"]:
        t0 = time.perf_counter()
        counts = ingest.run(args.xlsx, args.db)
        dt = time.perf_counter() - t0
        print(f"[ingest] {Path(args.xlsx).name} -> {args.db} in {dt:.1f}s")
        for table, n in counts.items():
            print(f"  {table:>14}: {n:,}")

    if stages["forecast"]:
        from planz import forecast
        t0 = time.perf_counter()
        info = forecast.run(args.db)
        dt = time.perf_counter() - t0
        print(f"[forecast] {info['series']} series x 52 weeks"
              f" ({info['forecast_rows']:,} rows) in {dt:.1f}s")
        for model, w in info["holdout_wape"].items():
            print(f"  holdout WAPE {model:>15}: {w:.1%}")

    if stages["mps"]:
        from planz import mps
        t0 = time.perf_counter()
        info = mps.run(args.db, plan_id=plan_mps, quantile=q)
        dt = time.perf_counter() - t0
        print(f"[mps] {plan_mps} solved + validated in {dt:.0f}s"
              f" (demand quantile: {q})")
        print(f"  total production: {info['total_production']:,.0f} u")
        print(f"  freight cost:     ${info['freight_cost']:,.0f}")
        print(f"  unmet demand:     {info['total_short']:,.0f} u")
        if q != "p50":
            # calculations FROM the quantile plan: head-to-head vs the P50
            # baseline, if one has been solved into this DB
            from planz import heuristic
            cmp_rows = heuristic.compare(args.db, "baseline", plan_mps)
            if cmp_rows[0][1]:
                print(f"  {'plan':<14} {'production':>12} {'freight':>12}"
                      f" {'unmet':>10} {'medWOSsup':>10}")
                for p, prod, cost, short, ws, _ in cmp_rows:
                    print(f"  {p:<14} {prod:>12,.0f}"
                          f" {'$' + format(cost, ',.0f'):>12}"
                          f" {short:>10,.0f}"
                          f" {format(ws, '.1f') if ws is not None else '-':>10}")

    if stages["scenario"]:
        import sqlite3
        if q != "p50":
            print("[scenario] note: the V2+V4 scenario is defined vs the P50"
                  " baseline — --quantile does not apply here")
        # the diff is meaningless without a solved P50 baseline (a fresh DB
        # run with --all --quantile p90 only has baseline_p90) — skip with a
        # pointer instead of printing the scenario's own totals as "deltas"
        try:
            _c = sqlite3.connect(args.db)
            has_base = _c.execute("SELECT COUNT(*) FROM mps WHERE"
                                  " plan_id = 'baseline'").fetchone()[0]
            _c.close()
        except sqlite3.OperationalError:
            has_base = 0
        if not has_base:
            print("[scenario] SKIPPED — no P50 'baseline' plan in this DB to"
                  " diff against. Solve it first:"
                  " python engine/run_pipeline.py --mps")
            stages["scenario"] = False
    if stages["scenario"]:
        from planz import scenario
        t0 = time.perf_counter()
        info = scenario.run(args.db)
        dt = time.perf_counter() - t0
        print(f"[scenario] V2+V4 enclosure shortage solved + validated in {dt:.0f}s")
        print(f"  volume delta:  {info['volume_delta']:+,.0f} u")
        print(f"  freight delta: ${info['freight_delta']:+,.0f}")
        print(f"  unmet delta:   {info['short_delta']:+,.0f} u")
        print(f"  supply position trails baseline through:"
              f" {info['last_trailing_week']}")
        print("  allocation of the 4,500 u/wk cap (V2 / V4):")
        for a in info["allocation"]:
            print(f"    {a['week']}: {a['v2_scen']:>7,.0f} /"
                  f" {a['v4_scen']:>7,.0f}   (baseline"
                  f" {a['v2_base']:,.0f} / {a['v4_base']:,.0f})")

    if stages["heuristic"]:
        from planz import heuristic
        t0 = time.perf_counter()
        heuristic.run(args.db, plan_id=plan_heur, quantile=q)
        dt = time.perf_counter() - t0
        print(f"[heuristic] greedy plan built + validated in {dt:.0f}s"
              f" (demand quantile: {q})")
        cmp_rows = heuristic.compare(args.db, plan_mps, plan_heur)
        if not cmp_rows[0][1]:
            # no MILP counterpart at this quantile — don't print a fabricated
            # zero-production row that reads like a plan serving all demand
            flag = "" if q == "p50" else f" --quantile {q}"
            cmp_rows = cmp_rows[1:]
            print(f"  (no '{plan_mps}' plan in this DB to compare against —"
                  f" solve it with: python engine/run_pipeline.py --mps{flag})")
        print(f"  {'plan':<14} {'production':>12} {'freight':>12}"
              f" {'unmet':>8} {'medWOSsup':>10} {'medWOSch':>9}")
        for p, prod, cost, short, ws, wc in cmp_rows:
            print(f"  {p:<14} {prod:>12,.0f} {'$' + format(cost, ',.0f'):>12}"
                  f" {short:>8,.0f}"
                  f" {format(ws, '.1f') if ws is not None else '-':>10}"
                  f" {format(wc, '.1f') if wc is not None else '-':>9}")

    if stages["signals"]:
        from planz import signals
        skipped: list = []
        extracted: dict = {}
        rejected: dict = {}
        found = signals.extract_inbox(args.db, skipped_out=skipped,
                                      extracted_out=extracted,
                                      rejected_out=rejected)
        print(f"[signals] {len(found)} events extracted (pending approval)")
        for name, reason in skipped:
            print(f"  {name:<26} SKIPPED ({reason}) — existing pending"
                  " rows for it are preserved")
        for name, reasons in sorted(rejected.items()):
            for r in reasons:
                print(f"  {name:<26} REFUSED: {r}")
        for name in sorted(n for n, c in extracted.items()
                           if c == 0 and n not in rejected):
            print(f"  {name:<26} read, but no planning content recognized")
        for e in found:
            print(f"  {e['source']:<26} {e['event_type']:<19}"
                  f" conf {e['confidence']:.2f}  {e['params']}")
        ev = signals.evaluate()
        print(f"  eval vs labeled fixtures [{ev['backend']}]:"
              f" precision {ev['precision']:.0%}, recall {ev['recall']:.0%}")
        if ev.get("skipped"):
            print(f"  {len(ev['skipped'])} image fixture(s) skipped —"
                  f" vision needs ANTHROPIC_API_KEY:"
                  f" {', '.join(ev['skipped'])}")

    if args.approve_signals:
        from planz import signals
        print(f"[signals] {signals.approve(args.db)} events approved (human;"
              " image events are excluded — approve those one-by-one with"
              " --approve-signal <id>)")

    if args.approve_signal:
        from planz import signals
        for sid in args.approve_signal:
            n = signals.approve_one(args.db, sid)
            print(f"[signals] id {sid}: "
                  + ("approved (human, targeted)" if n else
                     "not approved — no pending row with that id"))

    if args.reject_signals:
        from planz import signals
        print(f"[signals] {signals.reject_pending(args.db)} events rejected"
              " (human; survives re-extraction)")

    if stages["agents"]:
        from planz import agents
        t0 = time.perf_counter()
        out = agents.run_loop(args.db, auto_approve=args.auto_approve)
        dt = time.perf_counter() - t0
        print(f"[agents] loop finished in {dt:.0f}s -> {out['status']}")
        for line in out["trace"]:
            print("  " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
