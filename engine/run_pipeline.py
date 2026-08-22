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
    ap.add_argument("--all", action="store_true", help="run every stage")
    args = ap.parse_args(argv)

    stages = {k: (getattr(args, k) or args.all)
              for k in ("ingest", "forecast", "mps", "scenario", "heuristic")}
    if not any(stages.values()):
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
        info = mps.run(args.db, plan_id="baseline")
        dt = time.perf_counter() - t0
        print(f"[mps] baseline solved + validated in {dt:.0f}s")
        print(f"  total production: {info['total_production']:,.0f} u")
        print(f"  freight cost:     ${info['freight_cost']:,.0f}")
        print(f"  unmet demand:     {info['total_short']:,.0f} u")

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
        heuristic.run(args.db)
        dt = time.perf_counter() - t0
        print(f"[heuristic] greedy plan built + validated in {dt:.0f}s")
        print(f"  {'plan':<10} {'production':>12} {'freight':>12}"
              f" {'unmet':>8} {'medWOSsup':>10} {'medWOSch':>9}")
        for p, prod, cost, short, ws, wc in heuristic.compare(args.db):
            print(f"  {p:<10} {prod:>12,.0f} {'$' + format(cost, ',.0f'):>12}"
                  f" {short:>8,.0f}"
                  f" {format(ws, '.1f') if ws is not None else '-':>10}"
                  f" {format(wc, '.1f') if wc is not None else '-':>9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
