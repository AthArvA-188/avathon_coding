import { NextRequest, NextResponse } from "next/server";
import { rows } from "@/lib/db";

// Weekly plan matrix, capacity, freight and WOS trajectory for one plan_id.
export function GET(req: NextRequest) {
  const p = req.nextUrl.searchParams;
  // whichever plans have actually been solved into this DB — baseline,
  // scenario, heuristic, agentic, and any quantile variants (baseline_p90
  // via `--quantile p90`). The un-promoted agentic candidate stays hidden.
  const plans = (
    rows("SELECT DISTINCT plan_id FROM mps ORDER BY plan_id") as { plan_id: string }[]
  )
    .map((r) => r.plan_id)
    .filter((n) => n !== "agentic_candidate");
  const requested = p.get("plan") ?? "baseline";
  // fall back to a plan that actually exists (a fresh DB solved only with
  // --quantile p90 has no 'baseline'), keeping the invariant plan ∈ plans
  const plan = plans.includes(requested)
    ? requested
    : plans.includes("baseline")
      ? "baseline"
      : plans[0] ?? "baseline";
  const variant = p.get("variant") ?? "Variant V1";
  const geo = p.get("geo") ?? "Geo G1";

  const matrix = rows(
    `SELECT week_label AS week, variant, ROUND(production) AS units, packout
     FROM mps WHERE plan_id = ? ORDER BY week_label`,
    plan
  );
  const weekly = rows(
    `SELECT week_label AS week, ROUND(SUM(production)) AS production,
            SUM(packout) AS slots
     FROM mps WHERE plan_id = ? GROUP BY week_label ORDER BY week_label`,
    plan
  );
  const quarters = rows(
    `SELECT c.quarter_label AS q, ROUND(SUM(m.production)) AS production
     FROM mps m JOIN calendar c ON c.week_label = m.week_label
     WHERE m.plan_id = ? GROUP BY 1 ORDER BY 1`,
    plan
  );
  const freight = rows(
    `SELECT geo, mode, ROUND(SUM(units)) AS units, ROUND(SUM(cost)) AS cost
     FROM shipments WHERE plan_id = ? GROUP BY geo, mode ORDER BY cost DESC`,
    plan
  );
  const wos = rows(
    `SELECT week_label AS week, ROUND(on_hand) AS on_hand,
            ROUND(in_transit) AS in_transit, ROUND(ch3_inventory) AS ch3,
            ROUND(wos_supply, 1) AS wos_supply,
            ROUND(wos_channel, 1) AS wos_channel
     FROM inventory WHERE plan_id = ? AND variant = ? AND geo = ?
     ORDER BY week_label`,
    plan, variant, geo
  );
  const validation = rows(
    "SELECT check_name, status, detail FROM validation WHERE plan_id = ?",
    plan
  );
  return NextResponse.json({ plan, plans, matrix, weekly, quarters, freight, wos, validation });
}
