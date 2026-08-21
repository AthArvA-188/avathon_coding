import { NextResponse } from "next/server";
import { rows } from "@/lib/db";

export function GET() {
  const variants = rows<{ variant: string }>(
    "SELECT DISTINCT variant FROM forecast ORDER BY CAST(SUBSTR(variant, 10) AS INT)"
  ).map((r) => r.variant);
  const geos = rows<{ geo: string }>(
    "SELECT DISTINCT geo FROM forecast ORDER BY geo"
  ).map((r) => r.geo);
  const channels = rows<{ channel: string }>(
    "SELECT DISTINCT channel FROM forecast ORDER BY channel"
  ).map((r) => r.channel);
  const scores = rows(
    "SELECT model, scope_type, scope, wape, smape, bias FROM forecast_scores"
  );
  const params = Object.fromEntries(
    rows<{ key: string; value: string }>("SELECT key, value FROM params").map(
      (r) => [r.key, r.value]
    )
  );
  const hasScenario =
    rows("SELECT 1 FROM mps WHERE plan_id = 'scenario' LIMIT 1").length > 0;
  return NextResponse.json({ variants, geos, channels, scores, params, hasScenario });
}
