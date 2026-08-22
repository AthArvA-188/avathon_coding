"use client";
import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
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
import { Card, fmt, Meta, Sel, Stat, useJson } from "@/components/ui";

type Plan = {
  plan: string;
  plans: string[];
  matrix: { week: string; variant: string; units: number; packout: number }[];
  weekly: { week: string; production: number; slots: number }[];
  quarters: { q: string; production: number }[];
  freight: { geo: string; mode: string; units: number; cost: number }[];
  wos: {
    week: string;
    on_hand: number;
    in_transit: number;
    ch3: number;
    wos_supply: number;
    wos_channel: number;
  }[];
  validation: { check_name: string; status: string; detail: string }[];
};

// which forecast quantile a stored plan was solved against, from its id
const quantileOf = (plan: string) =>
  plan.endsWith("_p90") ? "P90" : plan.endsWith("_p10") ? "P10" : "P50";

export default function PlanPage() {
  const meta = useJson<Meta>("/api/meta");
  const [variant, setVariant] = useState("Variant V1");
  const [geo, setGeo] = useState("Geo G1");
  const [plan, setPlan] = useState("baseline");
  const data = useJson<Plan>(
    `/api/plan?plan=${encodeURIComponent(plan)}&variant=${encodeURIComponent(variant)}&geo=${encodeURIComponent(geo)}`
  );

  const grid = useMemo(() => {
    if (!data) return { weeks: [] as string[], variants: [] as string[], cell: {} as Record<string, number> };
    const weeks = [...new Set(data.matrix.map((m) => m.week))].sort();
    const variants = [...new Set(data.matrix.map((m) => m.variant))].sort(
      (a, b) => Number(a.slice(9)) - Number(b.slice(9))
    );
    const cell: Record<string, number> = {};
    for (const m of data.matrix) cell[`${m.week}|${m.variant}`] = m.units;
    return { weeks, variants, cell };
  }, [data]);

  const totalProd = data?.weekly.reduce((s, w) => s + w.production, 0);
  const totalFreight = data?.freight.reduce((s, f) => s + f.cost, 0);

  return (
    <div>
      <h1 className="text-xl font-semibold mb-1">MPS &amp; pack-out — {data?.plan ?? plan}</h1>
      <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-5">
        Solved against the {quantileOf(data?.plan ?? plan)} demand cube; every
        hard constraint re-verified by independent validators after the solve.
      </p>

      <HowTo
        dos={[
          <>Scroll the pack-out grid sideways and count filled cells in any row — never more than 4 (the slot cap), and the “slots” column keeps score.</>,
          <>Switch variant/geo under the WOS chart and watch the two lines against their 12- and 13-week targets.</>,
          <>Cross-check any stat here by asking the same question on <b>Ask the Planner</b> — it prints the SQL.</>,
          <>Switch the <b>Plan</b> picker to <code className="font-mono">baseline_p90</code> (solve it once with <code className="font-mono">python engine/run_pipeline.py --mps --quantile p90</code>) to see the high-case calculation: what the same factory can and cannot do if demand lands at P90.</>,
        ]}
        watch={[
          <>The quarters-at-cap stat: <b>on the P50 baseline, 3 of 4 quarters sit at exactly 224,000 units</b> — the year is capacity-bound, not demand-bound. That's the whole story in one number (the stat above always shows the <i>selected</i> plan's count).</>,
          <>Freight table: <b>on the P50 baseline, $4.68M of $5.22M is Air</b>. Air is the shadow price of scarce capacity — it swells to $5.17M at P90 and collapses to $2.4M at P10.</>,
          <>WOS lines eroding below target is <b>by design</b>: sell-through is protected first, buffers are spent. The strip below states the priority order.</>,
          <>The validators stat: every hard constraint re-verified <i>after</i> the solve by independent checks (the count varies by plan — scenario and agentic add per-hook checks).</>,
        ]}
      />

      <Provenance
        sources={`mps, shipments and inventory tables (plan_id '${data?.plan ?? plan}') written by engine/planz/mps.py; demand consumed from the forecast table (${quantileOf(data?.plan ?? plan)} column — quantile plans are solved with --quantile p90/p10 and live side by side with baseline).`}
        model={(data?.plan ?? plan).startsWith("heuristic")
          ? "Greedy heuristic (engine/planz/heuristic.py): a transparent week-by-week allocation under the same hard rules — capacity, pack-out slots, volume caps — and re-verified by the same independent validators as the MILP. It is the cross-check method: on the P50 cube it is cheaper on freight but leaves 99,455 units unmet vs the MILP baseline's zero (152,809 unmet at P90)."
          : "Mixed-integer program (PuLP + CBC, ~30 s): weekly production per variant, binary pack-out slots, shipments across each geo's freight frontier, two-tier inventory (DC on-hand + in-transit vs 12-WOS target; Channel-3 reseller stock vs 13-WOS). On the P50 baseline the greedy cross-check (--heuristic) is cheaper on freight but leaves 99,455 units unmet vs zero here; quantile plans re-run this identical model on the P90/P10 cube — at P90 even it leaves 33,067 units unmet."}
        params={[
          "Hard: 17,280 u/week · 224,000 u/quarter · ≤4 pack-out variants/week · volume caps · no ship that can't land in-horizon",
          "Objective priority: unmet demand ≫ channel WOS (13) > supply WOS (12) > freight > holding",
          "Opening state assumed at policy targets (D24, client question); WOS is run-out based",
          "Every solve re-verified by independent post-solve checks incl. a full inventory-balance replay (9 hard-constraint checks + one per scenario hook — the validators stat shows this plan's count)",
          "Quantile plans (baseline_p90/p10): opening inventory follows the D24 policy convention — WOS targets sized to the same cube the plan is solved on — so a P90 plan models a steady-state world at P90, not a P50 world surprised by P90 demand",
        ]}
        takeaway="Capacity, not demand, is the binding constraint: three quarters run at exactly the cap and buffers are consumed to protect sell-through."
      />

      <div className="flex flex-wrap items-end gap-4 mb-4">
        <Sel label="Plan" value={plan} onChange={setPlan}
             options={data?.plans?.length ? data.plans : [plan]} />
        {quantileOf(data?.plan ?? plan) !== "P50" && (
          <p className="text-xs text-amber-700 dark:text-amber-400 max-w-xl pb-1.5">
            This plan is solved against the {quantileOf(data?.plan ?? plan)} forecast —
            same capacity, slots, volume caps and validators, only the demand
            changes. Compare unmet demand with <b>baseline</b>: at the P90 high
            case the capacity wall, not the planning method, is what binds.
          </p>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-4 mb-6">
        <Stat label="total production" value={`${fmt(totalProd)} u`} />
        <Stat label="freight cost" value={`$${fmt(totalFreight)}`} />
        <Stat
          label="validators"
          value={`${data?.validation.filter((v) => v.status === "PASS").length ?? "–"}/${data?.validation.length ?? "–"} PASS`}
        />
        <Stat
          label="quarters at the 224,000 cap"
          value={`${data?.quarters.filter((q) => q.production >= 223_999).length ?? "–"} of 4`}
        />
      </div>

      <Card
        title="Weekly production vs capacity"
        note="Bars: total units packed out per week. Dashed line: 17,280 u weekly cap."
      >
        <div className="h-64">
          <ResponsiveContainer>
            <BarChart data={data?.weekly ?? []} margin={{ left: 10, right: 10 }}>
              <CartesianGrid strokeOpacity={0.15} vertical={false} />
              <XAxis dataKey="week" tick={{ fontSize: 10 }} minTickGap={50} />
              <YAxis tick={{ fontSize: 10 }} width={58}
                     tickFormatter={(v: number) => `${v / 1000}k`} />
              <Tooltip formatter={(v) => fmt(Number(v))} />
              <ReferenceLine y={17280} strokeDasharray="6 4" stroke="#888" />
              <Bar dataKey="production" fill="#eb6834" name="Production" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card
        title="Pack-out schedule"
        note="Units by variant and week; at most 4 variants may be packed out in any week. Scroll sideways."
      >
        <div className="overflow-x-auto">
          <table className="text-[10px] tabular-nums border-collapse">
            <thead>
              <tr>
                <th className="sticky left-0 bg-white dark:bg-zinc-900 text-left pr-2 py-1">week</th>
                {grid.variants.map((v) => (
                  <th key={v} className="px-1.5 text-right font-medium">
                    {v.replace("Variant ", "")}
                  </th>
                ))}
                <th className="pl-2 text-right">slots</th>
              </tr>
            </thead>
            <tbody>
              {grid.weeks.map((w) => {
                const slots = grid.variants.filter(
                  (v) => (grid.cell[`${w}|${v}`] ?? 0) > 0
                ).length;
                return (
                  <tr key={w} className="border-t border-zinc-100 dark:border-zinc-800">
                    <td className="sticky left-0 bg-white dark:bg-zinc-900 pr-2 py-0.5 font-mono">
                      {w}
                    </td>
                    {grid.variants.map((v) => {
                      const u = grid.cell[`${w}|${v}`] ?? 0;
                      return (
                        <td
                          key={v}
                          className={`px-1.5 text-right ${u > 0 ? "bg-orange-50 dark:bg-orange-950/40 text-zinc-900 dark:text-zinc-100" : "text-zinc-300 dark:text-zinc-700"}`}
                        >
                          {u > 0 ? fmt(u) : "·"}
                        </td>
                      );
                    })}
                    <td className="pl-2 text-right">{slots}/4</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <Card
        title="Freight by geo and mode"
        note="The solver picks from each geo's cost/speed frontier; Air appears where capacity scarcity forces just-in-time production."
      >
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-zinc-500">
              <th className="py-1.5">Geo</th>
              <th>Mode</th>
              <th className="text-right">Units</th>
              <th className="text-right">Cost</th>
            </tr>
          </thead>
          <tbody>
            {(data?.freight ?? []).map((f) => (
              <tr key={f.geo + f.mode} className="border-t border-zinc-200 dark:border-zinc-800">
                <td className="py-1.5">{f.geo}</td>
                <td>{f.mode}</td>
                <td className="text-right tabular-nums">{fmt(f.units)}</td>
                <td className="text-right tabular-nums">${fmt(f.cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card
        title="Inventory & weeks of supply"
        note={`Run-out WOS against the ${quantileOf(data?.plan ?? plan)} forecast (the same cube this plan was solved on). Targets: 12 (supply position), 13 (reseller channel). In a capacity-short year the buffers erode by design — sell-through is protected first.`}
      >
        <div className="flex flex-wrap gap-4 mb-4">
          <Sel label="Variant" value={variant} onChange={setVariant}
               options={meta?.variants ?? []} />
          <Sel label="Geo" value={geo} onChange={setGeo}
               options={meta?.geos ?? []} />
        </div>
        <div className="h-64">
          <ResponsiveContainer>
            <LineChart data={data?.wos ?? []} margin={{ left: 10, right: 10 }}>
              <CartesianGrid strokeOpacity={0.15} vertical={false} />
              <XAxis dataKey="week" tick={{ fontSize: 10 }} minTickGap={50} />
              <YAxis tick={{ fontSize: 10 }} width={40} />
              <Tooltip />
              <Legend />
              <ReferenceLine y={12} strokeDasharray="6 4" stroke="#888" />
              <ReferenceLine y={13} strokeDasharray="2 4" stroke="#888" />
              <Line dataKey="wos_supply" stroke="#2a78d6" dot={false}
                    strokeWidth={2} name="Supply WOS (target 12)" />
              <Line dataKey="wos_channel" stroke="#1baf7a" dot={false}
                    strokeWidth={2} name="Channel WOS (target 13)" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </div>
  );
}
