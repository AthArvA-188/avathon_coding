"use client";
import { useEffect, useState } from "react";

export function useJson<T>(url: string | null): T | null {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    if (!url) return;
    let alive = true;
    fetch(url)
      .then((r) => r.json())
      .then((d) => alive && setData(d))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, [url]);
  return data;
}

export const fmt = (n: number | null | undefined) =>
  n == null ? "–" : Math.round(n).toLocaleString("en-US");

export function Card({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 mb-6">
      <h2 className="font-semibold text-sm mb-0.5">{title}</h2>
      {note && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-3">{note}</p>
      )}
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-4 py-3">
      <div className="text-xl font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
        {label}
        {sub && <span className="block">{sub}</span>}
      </div>
    </div>
  );
}

export function Sel({
  label,
  value,
  onChange,
  options,
  allLabel,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  allLabel?: string;
}) {
  return (
    <label className="text-sm flex items-center gap-2">
      <span className="text-zinc-500 dark:text-zinc-400">{label}</span>
      <select
        className="rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {allLabel && <option value="all">{allLabel}</option>}
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

export type Meta = {
  variants: string[];
  geos: string[];
  channels: string[];
  scores: {
    model: string;
    scope_type: string;
    scope: string;
    wape: number;
    smape: number;
    bias: number;
  }[];
  params: Record<string, string>;
  hasScenario: boolean;
};
