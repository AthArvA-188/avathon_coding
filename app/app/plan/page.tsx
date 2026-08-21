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
import { Card, fmt, Meta, Sel, Stat, useJson } from "@/components/ui";

type Plan = {
  plan: string;
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

export default function PlanPage() {
  const meta = useJson<Meta>("/api/meta");
  const [variant, setVariant] = useState("Variant V1");
  const [geo, setGeo] = useState("Geo G1");
  const data = useJson<Plan>(
    `/api/plan?plan=baseline&variant=${encodeURIComponent(variant)}&geo=${encodeURIComponent(geo)}`
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
      <h1 className="text-xl font-semibold mb-1">MPS & pack-out — baseline</h1>
      <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-5">
        Solved by the MILP; every hard constraint re-verified by independent
        validators after the solve.
      </p>

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
        note="Run-out WOS against the P50 forecast. Targets: 12 (supply position), 13 (reseller channel). In a capacity-short year the buffers erode by design — sell-through is protected first."
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
