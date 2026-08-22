import { NextResponse } from "next/server";
import { rows } from "@/lib/db";
import fs from "fs";
import path from "path";

// Signals only (the agent trail lives at /api/agents). Params are decoded
// into human-readable fields: week offsets become fiscal week labels, and
// each event is checked against the labeled fixture expectations.

const stable = (obj: unknown): string =>
  JSON.stringify(obj, (_k, v) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.entries(v as object).sort())
      : v
  );

export function GET() {
  const have = new Set(
    rows<{ name: string }>(
      "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).map((r) => r.name)
  );
  if (!have.has("signals")) {
    return NextResponse.json({ available: false, signals: [] });
  }

  const horizon = rows<{ week_label: string }>(
    "SELECT week_label FROM calendar WHERE is_horizon = 1 ORDER BY week_label"
  ).map((r) => r.week_label);
  const week = (o: number) => horizon[o] ?? `offset ${o}`;

  // labeled expectations (the eval harness's ground truth)
  let labels: Record<string, { event_type: string; params: unknown }[]> = {};
  try {
    labels = JSON.parse(
      fs.readFileSync(
        path.join(process.cwd(), "..", "engine", "signals_inbox", "labels.json"),
        "utf-8"
      )
    );
  } catch {
    labels = {};
  }

  // vision provenance columns (D30) — older DBs may predate the migration
  const cols = new Set(
    rows<{ name: string }>("SELECT name FROM pragma_table_info('signals')")
      .map((r) => r.name)
  );
  const visionSel = cols.has("transcription") && cols.has("source_sha256")
    ? "transcription, source_sha256"
    : "'' AS transcription, '' AS source_sha256";

  const signals = rows(
    `SELECT id, source, event_type, params_json, evidence, backend,
            prompt_version, confidence, status, created_at, ${visionSel}
     FROM signals ORDER BY source, id`
  ).map((s) => {
    const p = JSON.parse(s.params_json as string) as Record<string, unknown>;
    const start = Number(p.start_offset ?? 0);
    const n = Number(p.n_weeks ?? 1);
    const windowLabel =
      n > 1 ? `${week(start)} – ${week(start + n - 1)}` : week(start);
    const facts: [string, string][] = [];
    if (p.variants)
      facts.push(["variants",
        (p.variants as string[]).map((v) => v.replace("Variant ", "")).join(" + ")]);
    if (p.variant)
      facts.push(["variant", String(p.variant).replace("Variant ", "")]);
    if (p.geo) facts.push(["geo", String(p.geo)]);
    if (p.mode) facts.push(["mode", String(p.mode)]);
    facts.push(["weeks", `${windowLabel} (${n} wk)`]);
    if (p.weekly_cap)
      facts.push(["cap", `${Number(p.weekly_cap).toLocaleString("en-US")} u/wk`]);
    if (p.multiplier) facts.push(["multiplier", `×${p.multiplier}`]);
    if (s.source_sha256)
      facts.push(["image sha256", `${String(s.source_sha256).slice(0, 12)}…`]);

    const expected = labels[s.source as string] ?? [];
    const label_match = expected.some(
      (e) => e.event_type === s.event_type && stable(e.params) === stable(p)
    );
    return { ...s, facts, label_match };
  });

  return NextResponse.json({ available: true, signals });
}
