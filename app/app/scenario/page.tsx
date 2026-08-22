"use client";
import { useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import HowTo from "@/components/HowTo";
import Provenance from "@/components/Provenance";
import { Card, fmt, Stat, useJson } from "@/components/ui";

type Diff = {
  totals: Record<"baseline" | "scenario",
    { production: number; freight: number; short: number }>;
  prod: { week: string; base: number; scen: number }[];
  position: { week: string; base: number; scen: number }[];
  allocation: { week: string; v2: number; v4: number }[];
  stockouts: { variant: string; base: number; scen: number }[];
  wosHit: { geo: string; weeks_worse: number; avg_wos_loss: number }[];
};

export default function ScenarioPage() {
  const [on, setOn] = useState(true);
  const d = useJson<Diff>("/api/scenario");
  const t = d?.totals;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-4 mb-1">
        <h1 className="text-xl font-semibold">V2+V4 enclosure shortage</h1>
        <label className="flex items-center gap-3 text-sm cursor-pointer select-none">
          <span className="text-zinc-500 dark:text-zinc-400">
            scenario {on ? "ON" : "OFF"}
          </span>
          <button
            role="switch"
            aria-checked={on}
            onClick={() => setOn(!on)}
            className={`w-11 h-6 rounded-full transition-colors ${on ? "bg-orange-500" : "bg-zinc-300 dark:bg-zinc-700"}`}
          >
            <span
              className={`block w-5 h-5 mt-0.5 rounded-full bg-white shadow transition-transform ${on ? "translate-x-5" : "translate-x-0.5"}`}
            />
          </button>
        </label>
      </div>
      <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-5 max-w-2xl">
        Variants V2 and V4 share an enclosure; combined production is capped at
        4,500 u/week for 2023W40–2023W45. Both plans are pre-solved — the toggle
        compares them instantly.
      </p>

      <HowTo
        dos={[
          <>Flip the toggle off and on — both plans are pre-solved, so the diff is instant.</>,
          <>Read the allocation table week by week: watch who gets the scarce 4,500 units.</>,
        ]}
        watch={[
          <>The headline deltas look boring — <b>−346 units, freight ~flat</b>. The real damage is in the recovery chart: supply position doesn't rejoin baseline until <b>2024W29</b> (≈ mid-April). A 6-week shortage, an 8-month scar.</>,
          <>The solver <b>alternates full-cap weeks</b> between V2 and V4 (batching preserves pack-out slots) and lands on an exact 50/50 split nobody asked it for.</>,
          <>Why no catch-up sooner: a factory already at capacity has nothing spare — that's the punchline of the whole assignment.</>,
        ]}
      />

      <Provenance
        sources="the same mps/shipments/inventory tables, under two plan_ids: 'baseline' and 'scenario' — both pre-solved by the pipeline, so this toggle is a query, not a re-solve."
        model="Identical MILP to the baseline plus one hard constraint: combined V2+V4 production ≤ 4,500 u/week for 2023W40–W45 (the brief's shared-enclosure shortage). The V2-vs-V4 split is not hand-picked — the WOS-equalizing objective allocates scarce units to whichever variant is closer to running out."
        params={[
          "Constrained window: first 6 weeks of CQ+1 (Jul–Aug, the pre-holiday build window)",
          "Observed allocation: alternating full-cap weeks (pack-out slot economics) → exact 50/50",
          "Validators re-checked incl. the shared-cap constraint (10 checks on this plan: the 9 base checks + the extra-cap check)",
        ]}
        takeaway="Volume and cost barely move (−346 u, ~flat freight) — the real damage is time: V2+V4 cover trails baseline for ~8 months because a factory at capacity cannot catch up."
      />

      {on && t && (
        <div className="grid gap-3 sm:grid-cols-4 mb-6">
          <Stat label="volume delta"
                value={`${t.scenario.production - t.baseline.production >= 0 ? "+" : ""}${fmt(t.scenario.production - t.baseline.production)} u`}
                sub="idle late-year capacity rebuilds most of the window loss" />
          <Stat label="freight delta"
                value={`$${fmt(t.scenario.freight - t.baseline.freight)}`}
                sub="within solver tolerance — effectively flat" />
          <Stat label="unmet demand delta"
                value={`${t.scenario.short - t.baseline.short >= 0 ? "+" : ""}${fmt(t.scenario.short - t.baseline.short)} u`} />
          <Stat label="supply position recovers" value="2024W29"
                sub="a 6-week shortage leaves an ~8-month scar" />
        </div>
      )}

      <Card
        title="V2+V4 weekly production"
        note={on ? "Blue: baseline. Orange: under the shared 4,500 u/wk cap (dashed line) for the first 6 weeks."
                 : "Baseline plan only — flip the toggle to overlay the shortage plan."}
      >
        <div className="h-64">
          <ResponsiveContainer>
            <LineChart data={d?.prod ?? []} margin={{ left: 10, right: 10 }}>
              <CartesianGrid strokeOpacity={0.15} vertical={false} />
              <XAxis dataKey="week" tick={{ fontSize: 10 }} minTickGap={50} />
              <YAxis tick={{ fontSize: 10 }} width={52}
                     tickFormatter={(v: number) => `${v / 1000}k`} />
              <Tooltip formatter={(v) => fmt(Number(v))} />
              <Legend />
              <ReferenceLine y={4500} strokeDasharray="6 4" stroke="#888" />
              <Line dataKey="base" stroke="#2a78d6" dot={false} strokeWidth={2} name="Baseline" />
              {on && (
                <Line dataKey="scen" stroke="#eb6834" dot={false} strokeWidth={2} name="Shortage plan" />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {on && (
        <>
          <Card
            title="Allocating the scarce 4,500 units"
            note="The solver alternates full-cap weeks between V2 and V4 — batching preserves pack-out slots — landing on an exact 50/50 split (13,500 u each) across the window."
          >
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-zinc-500">
                  <th className="py-1.5">Week</th>
                  <th className="text-right">V2</th>
                  <th className="text-right">V4</th>
                  <th className="text-right">Combined / cap</th>
                </tr>
              </thead>
              <tbody>
                {(d?.allocation ?? []).map((a) => (
                  <tr key={a.week} className="border-t border-zinc-200 dark:border-zinc-800">
                    <td className="py-1.5 font-mono text-xs">{a.week}</td>
                    <td className="text-right tabular-nums">{fmt(a.v2)}</td>
                    <td className="text-right tabular-nums">{fmt(a.v4)}</td>
                    <td className="text-right tabular-nums">
                      {fmt(a.v2 + a.v4)} / 4,500
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <Card
            title="V2+V4 supply position: the recovery curve"
            note="On-hand + in-transit under both plans. The gap opens during the 6 constrained weeks and doesn't close until 2024W29 — the factory has no spare capacity to catch up sooner."
          >
            <div className="h-64">
              <ResponsiveContainer>
                <LineChart data={d?.position ?? []} margin={{ left: 10, right: 10 }}>
                  <CartesianGrid strokeOpacity={0.15} vertical={false} />
                  <XAxis dataKey="week" tick={{ fontSize: 10 }} minTickGap={50} />
                  <YAxis tick={{ fontSize: 10 }} width={58}
                         tickFormatter={(v: number) => `${v / 1000}k`} />
                  <Tooltip formatter={(v) => fmt(Number(v))} />
                  <Legend />
                  <Line dataKey="base" stroke="#2a78d6" dot={false} strokeWidth={2} name="Baseline" />
                  <Line dataKey="scen" stroke="#eb6834" dot={false} strokeWidth={2} name="Shortage plan" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <div className="grid gap-6 md:grid-cols-2">
            <Card title="Stockout weeks by variant"
                  note="Weeks with any unmet demand. Both plans protect sell-through almost completely.">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-zinc-500">
                    <th className="py-1.5">Variant</th>
                    <th className="text-right">Baseline</th>
                    <th className="text-right">Shortage</th>
                  </tr>
                </thead>
                <tbody>
                  {(d?.stockouts?.length ? d.stockouts : [{ variant: "—", base: 0, scen: 0 }]).map(
                    (s) => (
                      <tr key={s.variant} className="border-t border-zinc-200 dark:border-zinc-800">
                        <td className="py-1.5">{s.variant}</td>
                        <td className="text-right tabular-nums">{s.base}</td>
                        <td className="text-right tabular-nums">{s.scen}</td>
                      </tr>
                    )
                  )}
                </tbody>
              </table>
            </Card>
            <Card title="WOS impact by geo (V2+V4)"
                  note="Which geos absorb the hit: weeks materially below baseline coverage, and the average WOS lost.">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-zinc-500">
                    <th className="py-1.5">Geo</th>
                    <th className="text-right">Weeks worse</th>
                    <th className="text-right">Avg WOS lost</th>
                  </tr>
                </thead>
                <tbody>
                  {(d?.wosHit ?? []).map((w) => (
                    <tr key={w.geo} className="border-t border-zinc-200 dark:border-zinc-800">
                      <td className="py-1.5">{w.geo}</td>
                      <td className="text-right tabular-nums">{w.weeks_worse}</td>
                      <td className="text-right tabular-nums">{w.avg_wos_loss}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
