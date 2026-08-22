import { NextResponse } from "next/server";
import { rows } from "@/lib/db";

// Signals inbox + agentic audit trail. Both tables only exist after
// `--signals` / `--agents` have run at least once — report that cleanly.
export function GET() {
  const have = new Set(
    rows<{ name: string }>(
      "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).map((r) => r.name)
  );
  const signals = have.has("signals")
    ? rows(
        `SELECT id, source, event_type, params_json, evidence, backend,
                prompt_version, confidence, status, created_at
         FROM signals ORDER BY source, id`
      )
    : [];
  const log = have.has("agent_log")
    ? rows("SELECT ts, agent, action, detail, outcome FROM agent_log ORDER BY id")
    : [];
  const agentic = have.has("mps")
    ? rows(
        `SELECT ROUND(SUM(production)) AS production FROM mps
         WHERE plan_id = 'agentic'`
      )[0]
    : null;
  const validation = have.has("validation")
    ? rows(
        "SELECT check_name, status FROM validation WHERE plan_id = 'agentic'"
      )
    : [];
  return NextResponse.json({
    available: have.has("signals"),
    signals,
    log,
    agenticProduction: (agentic?.production as number) ?? null,
    validation,
  });
}
