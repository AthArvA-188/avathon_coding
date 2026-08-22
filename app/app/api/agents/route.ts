import { NextResponse } from "next/server";
import { rows } from "@/lib/db";

// The agentic loop's audit trail + the published agentic plan summary.
export function GET() {
  const have = new Set(
    rows<{ name: string }>(
      "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).map((r) => r.name)
  );
  const log = have.has("agent_log")
    ? rows("SELECT ts, agent, action, detail, outcome FROM agent_log ORDER BY id")
    : [];
  const agentic = have.has("mps")
    ? rows<{ production: number }>(
        "SELECT ROUND(SUM(production)) AS production FROM mps WHERE plan_id = 'agentic'"
      )[0]?.production ?? null
    : null;
  const baseline = have.has("mps")
    ? rows<{ production: number }>(
        "SELECT ROUND(SUM(production)) AS production FROM mps WHERE plan_id = 'baseline'"
      )[0]?.production ?? null
    : null;
  const validation = have.has("validation")
    ? rows("SELECT check_name, status FROM validation WHERE plan_id = 'agentic'")
    : [];
  const short = have.has("inventory")
    ? rows<{ s: number }>(
        `SELECT ROUND(COALESCE(SUM(short_direct + short_ch3), 0)) AS s
         FROM inventory WHERE plan_id = 'agentic'`
      )[0]?.s ?? null
    : null;
  return NextResponse.json({
    available: have.has("agent_log"),
    log,
    agenticProduction: agentic,
    baselineProduction: baseline,
    unmet: short,
    validation,
  });
}
