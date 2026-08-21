import { NextRequest, NextResponse } from "next/server";
import { rows } from "@/lib/db";

// Aggregated actuals + forecast for the selected slice ("all" = no filter).
export function GET(req: NextRequest) {
  const p = req.nextUrl.searchParams;
  const variant = p.get("variant") ?? "all";
  const geo = p.get("geo") ?? "all";
  const channel = p.get("channel") ?? "all";

  const cond: string[] = [];
  const args: string[] = [];
  if (variant !== "all") { cond.push("variant = ?"); args.push(variant); }
  if (geo !== "all") { cond.push("geo = ?"); args.push(geo); }
  if (channel !== "all") { cond.push("channel = ?"); args.push(channel); }
  const fcWhere = cond.length ? "WHERE " + cond.join(" AND ") : "";

  const aCond: string[] = ["a.metric = 'ST'"];
  if (variant !== "all") { aCond.push("s.variant = ?"); }
  if (geo !== "all") { aCond.push("s.geo = ?"); }
  if (channel !== "all") { aCond.push("s.channel = ?"); }

  const actuals = rows(
    `SELECT a.week_label AS week, ROUND(SUM(a.units)) AS units
     FROM actuals a JOIN series s USING (series_id)
     WHERE ${aCond.join(" AND ")}
     GROUP BY a.week_label ORDER BY a.week_label`,
    ...args
  );
  const forecast = rows(
    `SELECT week_label AS week, ROUND(SUM(p10)) AS p10,
            ROUND(SUM(p50)) AS p50, ROUND(SUM(p90)) AS p90
     FROM forecast ${fcWhere}
     GROUP BY week_label ORDER BY week_label`,
    ...args
  );
  return NextResponse.json({ actuals, forecast });
}
