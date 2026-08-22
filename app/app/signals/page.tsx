"use client";
import Provenance from "@/components/Provenance";
import { Card, Stat, useJson } from "@/components/ui";

type Signal = {
  id: number; source: string; event_type: string; evidence: string;
  backend: string; prompt_version: string; confidence: number; status: string;
  facts: [string, string][]; label_match: boolean;
};
type Data = { available: boolean; signals: Signal[] };

const statusStyle: Record<string, string> = {
  approved: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  pending: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  rejected: "bg-rose-100 text-rose-900 dark:bg-rose-950 dark:text-rose-200",
};
const typeLabel: Record<string, string> = {
  supply_cap: "Supply cap",
  demand_shock: "Demand shock",
  freight_disruption: "Freight disruption",
};

export default function SignalsPage() {
  const d = useJson<Data>("/api/signals");

  if (d && !d.available) {
    return (
      <div className="max-w-2xl">
        <h1 className="text-xl font-semibold mb-2">Signals</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          No signals extracted yet — run{" "}
          <code className="font-mono">python engine/run_pipeline.py --signals</code>{" "}
          and refresh.
        </p>
      </div>
    );
  }

  const counts = { approved: 0, pending: 0, rejected: 0 } as Record<string, number>;
  d?.signals.forEach((s) => (counts[s.status] = (counts[s.status] ?? 0) + 1));
  const matched = d?.signals.filter((s) => s.label_match).length ?? 0;

  return (
    <div>
      <h1 className="text-xl font-semibold mb-1">Signals</h1>
      <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-4 max-w-2xl">
        Unstructured planner messages (supplier emails, retailer notes,
        carrier advisories) turned into typed, auditable planning events.
        Approval is a human act; the agentic loop that consumes these lives on
        its own page.
      </p>

      <Provenance
        sources="signals table in planz.db, extracted from the message files in engine/signals_inbox/; expectations from labels.json (the eval ground truth)."
        model="Pluggable extractor (llm.py): claude-sonnet-5 when ANTHROPIC_API_KEY is set, offline rules-v1 otherwise — the backend column shows which produced each row. Every event passes a sanitize boundary (known entities, horizon bounds, multiplier limits) and the evidence quote must appear verbatim in the source or confidence drops to 0."
        params={[
          "Auto-approval floor: confidence ≥ 0.8 — and only when explicitly requested",
          "Statuses survive re-extraction (content-hash keyed); rejections are permanent",
          "Prompt versions are provenance: v2 scored 14% recall and was rejected by the eval gate; v3 scores 100%/100%",
        ]}
        takeaway="Each card shows the event's decoded values (variants, weeks as fiscal labels, caps/multipliers) plus whether it matches the labeled expectation — nothing here has touched a plan unless its status is 'approved'."
      />

      <div className="grid gap-3 sm:grid-cols-4 mb-6">
        <Stat label="events" value={`${d?.signals.length ?? "–"}`} />
        <Stat label="approved / pending / rejected"
              value={`${counts.approved} / ${counts.pending} / ${counts.rejected}`} />
        <Stat label="match the labeled expectation"
              value={d ? `${matched} of ${d.signals.length}` : "–"} />
        <Stat label="extractor"
              value={d?.signals[0] ? `${d.signals[0].backend}` : "–"}
              sub={d?.signals[0] ? `prompt ${d.signals[0].prompt_version}` : undefined} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {(d?.signals ?? []).map((s) => (
          <Card
            key={s.id}
            title={`${typeLabel[s.event_type] ?? s.event_type} — ${s.source}`}
            note={`backend ${s.backend} · prompt ${s.prompt_version} · confidence ${s.confidence.toFixed(2)}`}
          >
            <div className="flex flex-wrap gap-2 mb-3">
              {s.facts.map(([k, v]) => (
                <span key={k}
                      className="inline-flex items-baseline gap-1.5 rounded-md bg-zinc-100 dark:bg-zinc-800 px-2.5 py-1 text-[12px]">
                  <span className="text-zinc-500 dark:text-zinc-400 uppercase text-[9.5px] tracking-wide">{k}</span>
                  <span className="font-medium tabular-nums">{v}</span>
                </span>
              ))}
            </div>
            <p className="text-[12.5px] text-zinc-500 dark:text-zinc-400 italic mb-3">
              “{s.evidence}”
            </p>
            <div className="flex items-center gap-2">
              <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${statusStyle[s.status] ?? ""}`}>
                {s.status}
              </span>
              <span className={`text-[11px] font-medium ${s.label_match ? "text-emerald-700 dark:text-emerald-400" : "text-zinc-400"}`}>
                {s.label_match ? "✓ matches labeled expectation" : "no matching label"}
              </span>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
