"use client";
import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, fmt, Meta, Sel, useJson } from "@/components/ui";

type Series = {
  actuals: { week: string; units: number }[];
  forecast: { week: string; p10: number; p50: number; p90: number }[];
};

export default function ForecastPage() {
  const meta = useJson<Meta>("/api/meta");
  const [variant, setVariant] = useState("all");
  const [geo, setGeo] = useState("all");
  const [channel, setChannel] = useState("all");
  const data = useJson<Series>(
    `/api/forecast?variant=${encodeURIComponent(variant)}&geo=${encodeURIComponent(geo)}&channel=${encodeURIComponent(channel)}`
  );

  const chart = useMemo(() => {
    if (!data) return [];
    const byWeek: Record<string, Record<string, number | string>> = {};
    for (const a of data.actuals) byWeek[a.week] = { week: a.week, actual: a.units };
    for (const f of data.forecast)
      byWeek[f.week] = { ...(byWeek[f.week] ?? { week: f.week }), ...f };
    return Object.values(byWeek).sort((a, b) =>
      String(a.week).localeCompare(String(b.week))
    );
  }, [data]);

  const scores = meta?.scores.filter(
    (s) =>
      (variant === "all" && s.scope_type === "overall") ||
      (variant !== "all" && s.scope_type === "variant" && s.scope === variant)
  );

  return (
    <div>
      <h1 className="text-xl font-semibold mb-1">Demand forecast</h1>
      <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-5">
        Net sell-through, actuals 2021W41–2023W39 and forecast 2023W40–2024W39.
        Weeks are fiscal (year starts ~October).
      </p>
      <div className="flex flex-wrap gap-4 mb-5">
        <Sel label="Variant" value={variant} onChange={setVariant}
             options={meta?.variants ?? []} allLabel="All variants" />
        <Sel label="Geo" value={geo} onChange={setGeo}
             options={meta?.geos ?? []} allLabel="All geos" />
        <Sel label="Channel" value={channel} onChange={setChannel}
             options={meta?.channels ?? []} allLabel="All channels" />
      </div>

      <Card
        title="Actuals & forecast"
        note="Solid: actuals and P50. Dashed: P10/P90 uncertainty band (sum of series quantiles)."
      >
        <div className="h-80">
          <ResponsiveContainer>
            <LineChart data={chart} margin={{ left: 10, right: 10 }}>
              <CartesianGrid strokeOpacity={0.15} vertical={false} />
              <XAxis dataKey="week" tick={{ fontSize: 10 }} minTickGap={60} />
              <YAxis tick={{ fontSize: 10 }} width={58}
                     tickFormatter={(v: number) => (v >= 1000 ? `${v / 1000}k` : String(v))} />
              <Tooltip formatter={(v) => fmt(Number(v))} />
              <Legend />
              <Line dataKey="actual" stroke="#2a78d6" dot={false} strokeWidth={2} name="Actuals" />
              <Line dataKey="p50" stroke="#eb6834" dot={false} strokeWidth={2} name="Forecast P50" />
              <Line dataKey="p10" stroke="#eb6834" dot={false} strokeWidth={1}
                    strokeDasharray="4 3" strokeOpacity={0.6} name="P10" />
              <Line dataKey="p90" stroke="#eb6834" dot={false} strokeWidth={1}
                    strokeDasharray="4 3" strokeOpacity={0.6} name="P90" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card
        title="Holdout accuracy (2023W27–2023W39)"
        note="Scored on 13 held-out weeks. WAPE = total miss ÷ total actual; bias > 0 means over-forecasting."
      >
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-zinc-500">
              <th className="py-1.5">Model</th>
              <th className="text-right">WAPE</th>
              <th className="text-right">sMAPE</th>
              <th className="text-right">Bias</th>
            </tr>
          </thead>
          <tbody>
            {(scores ?? []).map((s) => (
              <tr key={s.model} className="border-t border-zinc-200 dark:border-zinc-800">
                <td className="py-1.5">{s.model}</td>
                <td className="text-right tabular-nums">{(s.wape * 100).toFixed(1)}%</td>
                <td className="text-right tabular-nums">{(s.smape * 100).toFixed(1)}%</td>
                <td className="text-right tabular-nums">
                  {s.bias >= 0 ? "+" : ""}
                  {(s.bias * 100).toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
