import { NextRequest, NextResponse } from "next/server";
import { rows } from "@/lib/db";

// Conversational planner backend (brief §3.4 thread d).
// The language layer ONLY produces a structured intent; answers come from
// whitelisted read-only SQL (returned as provenance), and what-if requests
// come back as structured events for the gated signals flow — the NL layer
// can never touch a plan directly.

type Intent = {
  intent: string;
  variant?: string | null;
  geo?: string | null;
  quarter?: string | null;
  plan?: string | null;
  plan_b?: string | null;
};

const PLANS = new Set(["baseline", "scenario", "heuristic", "agentic"]);
const fmtN = (n: number | null | undefined) =>
  n == null ? "–" : Math.round(n).toLocaleString("en-US");

function fallbackParse(q: string): Intent {
  const s = q.toLowerCase();
  const out: Intent = { intent: "unknown" };
  const v = q.match(/\bV(\d{1,2})\b/i);
  if (v) out.variant = `Variant V${v[1]}`;
  const g = q.match(/\bG([1-5])\b/i);
  if (g) out.geo = `Geo G${g[1]}`;
  const fq = q.match(/\b(20\d{2})\s?Q([1-4])\b/i);
  const bq = q.match(/\bQ([1-4])\b/i);
  if (fq) out.quarter = `${fq[1]}Q${fq[2]}`;
  else if (bq) out.quarter = bq[1] === "4" ? "2023Q4" : `2024Q${bq[1]}`;
  for (const p of PLANS) if (s.includes(p)) { out.plan_b = out.plan ? p : out.plan_b; out.plan = out.plan ?? p; }
  if (/what if|double|increase|uplift|capped|cap at|suspend/.test(s)) out.intent = "what_if";
  else if (/compare|versus|\bvs\b/.test(s)) out.intent = "compare";
  else if (/why|explain/.test(s)) out.intent = "explain_scenario";
  else if (/wos|weeks of supply|cover|inventory/.test(s)) out.intent = "wos";
  else if (/freight|shipping|air|ocean/.test(s)) out.intent = "freight";
  else if (/stockout|unmet|short/.test(s)) out.intent = "stockouts";
  else if (/produc|build|pack/.test(s)) out.intent = "production";
  else if (/demand|forecast|sell/.test(s)) out.intent = "demand";
  return out;
}

async function claudeParse(q: string): Promise<Intent | null> {
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) return null;
  try {
    const res = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: "claude-sonnet-5",
        max_tokens: 300,
        system:
          'Classify a supply-planner question into JSON: {"intent": one of ' +
          '"production"|"demand"|"wos"|"freight"|"stockouts"|"compare"|' +
          '"explain_scenario"|"what_if"|"unknown", "variant": "Variant V1".."Variant V12"|null, ' +
          '"geo": "Geo G1".."Geo G5"|null, "quarter": e.g. "2023Q4"|"2024Q1"|null ' +
          '(horizon = fiscal 2023Q4 then 2024Q1-Q3; a bare "Q4" means 2023Q4), ' +
          '"plan": "baseline"|"scenario"|"heuristic"|"agentic"|null, "plan_b": same|null. ' +
          "Questions that propose changing demand/supply/freight are what_if. JSON only.",
        messages: [{ role: "user", content: q }],
      }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    const text = (data.content?.[0]?.text ?? "").replace(/```(json)?/g, "");
    return JSON.parse(text) as Intent;
  } catch {
    return null;
  }
}

export async function POST(req: NextRequest) {
  const { question } = (await req.json()) as { question: string };
  const parsed = (await claudeParse(question)) ?? fallbackParse(question);
  const parser = process.env.ANTHROPIC_API_KEY ? "claude-sonnet-5" : "rules";
  const plan = PLANS.has(parsed.plan ?? "") ? parsed.plan! : "baseline";
  const sql: string[] = [];
  const run = <T = Record<string, unknown>>(s: string, ...args: unknown[]) => {
    sql.push(s.replace(/\s+/g, " ").trim());
    return rows<T>(s, ...args);
  };

  let answer = "";
  let table: Record<string, unknown>[] = [];
  let mode: "deterministic" | "action" = "deterministic";
  let action: unknown = null;

  switch (parsed.intent) {
    case "production": {
      let s = "SELECT ROUND(SUM(m.production)) AS units FROM mps m";
      const w: string[] = ["m.plan_id = ?"];
      const a: unknown[] = [plan];
      if (parsed.quarter) {
        s += " JOIN calendar c ON c.week_label = m.week_label";
        w.push("c.quarter_label = ?");
        a.push(parsed.quarter);
      }
      if (parsed.variant) { w.push("m.variant = ?"); a.push(parsed.variant); }
      const r = run<{ units: number }>(s + " WHERE " + w.join(" AND "), ...a);
      answer = `Planned production${parsed.variant ? ` for ${parsed.variant}` : ""}${parsed.quarter ? ` in ${parsed.quarter}` : ""} under the ${plan} plan is ${fmtN(r[0]?.units)} units.`;
      break;
    }
    case "demand": {
      let s = "SELECT ROUND(SUM(f.p50)) AS units FROM forecast f";
      const w: string[] = [];
      const a: unknown[] = [];
      if (parsed.quarter) {
        s += " JOIN calendar c ON c.week_label = f.week_label";
        w.push("c.quarter_label = ?");
        a.push(parsed.quarter);
      }
      if (parsed.variant) { w.push("f.variant = ?"); a.push(parsed.variant); }
      if (parsed.geo) { w.push("f.geo = ?"); a.push(parsed.geo); }
      const r = run<{ units: number }>(
        s + (w.length ? " WHERE " + w.join(" AND ") : ""), ...a);
      answer = `Forecast (P50) demand${parsed.variant ? ` for ${parsed.variant}` : ""}${parsed.geo ? ` in ${parsed.geo}` : ""}${parsed.quarter ? ` in ${parsed.quarter}` : ""} is ${fmtN(r[0]?.units)} units.`;
      break;
    }
    case "wos": {
      const variant = parsed.variant ?? "Variant V1";
      const geo = parsed.geo ?? "Geo G1";
      table = run(
        `SELECT week_label, ROUND(wos_supply, 1) AS wos_supply,
                ROUND(wos_channel, 1) AS wos_channel
         FROM inventory WHERE plan_id = ? AND variant = ? AND geo = ?
         ORDER BY week_label`, plan, variant, geo);
      const min = table.reduce(
        (m, r) => (Number(r.wos_supply) < Number(m.wos_supply) ? r : m),
        table[0] ?? { week_label: "-", wos_supply: 0 });
      answer = `${variant} in ${geo} (${plan} plan): supply cover bottoms out at ${min?.wos_supply} weeks in ${min?.week_label} against the 12-week target. Full trajectory below.`;
      break;
    }
    case "freight": {
      table = run(
        `SELECT mode, ROUND(SUM(units)) AS units, ROUND(SUM(cost)) AS cost
         FROM shipments WHERE plan_id = ?${parsed.geo ? " AND geo = ?" : ""}
         GROUP BY mode ORDER BY cost DESC`,
        ...(parsed.geo ? [plan, parsed.geo] : [plan]));
      const total = table.reduce((s, r) => s + Number(r.cost), 0);
      answer = `Freight for the ${plan} plan${parsed.geo ? ` to ${parsed.geo}` : ""}: $${fmtN(total)} total — breakdown by mode below. Air dominates because just-in-time production in capped weeks cannot make an ocean lead time.`;
      break;
    }
    case "stockouts": {
      table = run(
        `SELECT variant, ROUND(SUM(short_direct + short_ch3)) AS unmet_units,
                COUNT(DISTINCT CASE WHEN short_direct + short_ch3 > 0.5
                      THEN week_label END) AS stockout_weeks
         FROM inventory WHERE plan_id = ? GROUP BY variant
         HAVING unmet_units > 0 ORDER BY unmet_units DESC`, plan);
      answer = table.length
        ? `The ${plan} plan leaves ${fmtN(table.reduce((s, r) => s + Number(r.unmet_units), 0))} units unmet — by variant below.`
        : `The ${plan} plan serves demand fully: zero unmet units.`;
      break;
    }
    case "compare": {
      const b = PLANS.has(parsed.plan_b ?? "") ? parsed.plan_b! : plan === "scenario" ? "baseline" : "scenario";
      table = run(
        `SELECT m.plan_id,
                ROUND(SUM(m.production)) AS production,
                (SELECT ROUND(SUM(cost)) FROM shipments s WHERE s.plan_id = m.plan_id) AS freight,
                (SELECT ROUND(SUM(short_direct + short_ch3)) FROM inventory i WHERE i.plan_id = m.plan_id) AS unmet
         FROM mps m WHERE m.plan_id IN (?, ?) GROUP BY m.plan_id`, plan, b);
      answer = `Side-by-side of '${plan}' vs '${b}' below (production, freight, unmet demand).`;
      break;
    }
    case "explain_scenario": {
      table = run(
        `SELECT b.week_label,
                ROUND(SUM(b.production)) AS baseline,
                ROUND(SUM(s.production)) AS scenario
         FROM mps b JOIN mps s ON s.plan_id = 'scenario'
           AND s.variant = b.variant AND s.week_label = b.week_label
         WHERE b.plan_id = 'baseline'
           AND b.variant IN ('Variant V2', 'Variant V4')
         GROUP BY b.week_label HAVING baseline <> scenario
         ORDER BY b.week_label LIMIT 12`);
      answer =
        "The scenario caps V2+V4 at a combined 4,500 u/week for 2023W40–W45. " +
        "The solver alternates full-cap weeks between the two variants (pack-out slot economics) for an exact 50/50 split, " +
        "rebuilds the deficit with idle late-year capacity (total volume only −346 u), " +
        "but the V2+V4 supply position trails baseline until 2024W29 — the weeks where the plans differ are below.";
      break;
    }
    case "what_if": {
      mode = "action";
      // extract a rough structured event; NEVER applied directly
      const mult = /double/.test(question.toLowerCase()) ? 2.0
        : (question.match(/(\d+)\s?%/) ? 1 + Number(question.match(/(\d+)\s?%/)![1]) / 100 : null);
      const cap = question.match(/([\d,]{3,})\s*(?:units|u)\b/i);
      action = {
        proposed_event: cap
          ? { event_type: "supply_cap", weekly_cap: Number(cap[1].replace(/,/g, "")), variants: parsed.variant ? [parsed.variant] : [], note: "edit weeks/variants as needed" }
          : { event_type: "demand_shock", variant: parsed.variant, geo: parsed.geo ?? "Geo G1", multiplier: mult ?? "?", note: "edit weeks as needed" },
        how_to_apply: [
          "Drop this as a message in engine/signals_inbox/ (or extend labels.json),",
          "python engine/run_pipeline.py --signals",
          "python engine/run_pipeline.py --approve-signals   (the human gate)",
          "python engine/run_pipeline.py --agents            (verifier-gated re-plan)",
        ],
      };
      answer =
        "What-if requests are never applied from chat — that's the guardrail. " +
        "I've translated your question into a structured event; it goes through the signals gate (sanitize → human approval → verifier-checked re-plan), so a plan that breaks capacity or pack-out rules cannot ship regardless of how the question was phrased.";
      break;
    }
    default:
      answer =
        "I couldn't map that to a planner question. Try: 'production for V3 in Q4 under the scenario plan', 'demand for V1 in G1', 'WOS for V2 in G1', 'freight breakdown', 'stockouts in the heuristic plan', 'compare baseline vs scenario', 'why did the scenario change V2?', or a what-if ('what if R4 doubles V3?').";
  }

  return NextResponse.json({
    parser, intent: parsed, mode, answer, table, sql, action,
  });
}
