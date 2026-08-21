import { NextResponse } from "next/server";
import { rows } from "@/lib/db";

const V24 = ["Variant V2", "Variant V4"];

// Baseline-vs-shortage diff: totals, weekly V2+V4 production and supply
// position under both plans, stockout weeks, per-geo WOS impact.
export function GET() {
  const totals = Object.fromEntries(
    ["baseline", "scenario"].map((plan) => [
      plan,
      {
        production: rows<{ v: number }>(
          "SELECT ROUND(SUM(production)) AS v FROM mps WHERE plan_id = ?",
          plan
        )[0]?.v ?? 0,
        freight: rows<{ v: number }>(
          "SELECT ROUND(SUM(cost)) AS v FROM shipments WHERE plan_id = ?",
          plan
        )[0]?.v ?? 0,
        short: rows<{ v: number }>(
          "SELECT ROUND(SUM(short_direct + short_ch3)) AS v FROM inventory WHERE plan_id = ?",
          plan
        )[0]?.v ?? 0,
      },
    ])
  );

  const prod = rows(
    `SELECT b.week_label AS week,
            ROUND(SUM(b.production)) AS base,
            ROUND(SUM(s.production)) AS scen
     FROM mps b JOIN mps s ON s.plan_id = 'scenario'
       AND s.variant = b.variant AND s.week_label = b.week_label
     WHERE b.plan_id = 'baseline' AND b.variant IN (?, ?)
     GROUP BY b.week_label ORDER BY b.week_label`,
    ...V24
  );
  const position = rows(
    `SELECT b.week_label AS week,
            ROUND(SUM(b.on_hand + b.in_transit)) AS base,
            ROUND(SUM(s.on_hand + s.in_transit)) AS scen
     FROM inventory b JOIN inventory s ON s.plan_id = 'scenario'
       AND s.variant = b.variant AND s.geo = b.geo
       AND s.week_label = b.week_label
     WHERE b.plan_id = 'baseline' AND b.variant IN (?, ?)
     GROUP BY b.week_label ORDER BY b.week_label`,
    ...V24
  );
  const allocation = rows(
    `SELECT week_label AS week,
            ROUND(SUM(CASE WHEN variant = 'Variant V2' THEN production ELSE 0 END)) AS v2,
            ROUND(SUM(CASE WHEN variant = 'Variant V4' THEN production ELSE 0 END)) AS v4
     FROM mps WHERE plan_id = 'scenario' AND week_label <= '2023W45'
     GROUP BY week_label ORDER BY week_label`
  );
  const stockouts = rows(
    `SELECT variant,
            SUM(CASE WHEN plan_id = 'baseline' AND short_direct + short_ch3 > 0.5 THEN 1 ELSE 0 END) AS base,
            SUM(CASE WHEN plan_id = 'scenario' AND short_direct + short_ch3 > 0.5 THEN 1 ELSE 0 END) AS scen
     FROM (SELECT plan_id, variant, week_label,
                  SUM(short_direct) AS short_direct, SUM(short_ch3) AS short_ch3
           FROM inventory GROUP BY plan_id, variant, week_label)
     GROUP BY variant HAVING base + scen > 0`
  );
  const wosHit = rows(
    `SELECT b.geo, SUM(CASE WHEN s.wos_supply < b.wos_supply - 0.5 THEN 1 ELSE 0 END) AS weeks_worse,
            ROUND(AVG(b.wos_supply - s.wos_supply), 2) AS avg_wos_loss
     FROM inventory b JOIN inventory s ON s.plan_id = 'scenario'
       AND s.variant = b.variant AND s.geo = b.geo AND s.week_label = b.week_label
     WHERE b.plan_id = 'baseline' AND b.variant IN (?, ?)
     GROUP BY b.geo ORDER BY avg_wos_loss DESC`,
    ...V24
  );
  return NextResponse.json({ totals, prod, position, allocation, stockouts, wosHit });
}
