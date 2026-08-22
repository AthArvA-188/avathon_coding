"use client";
import { Card, fmt, Stat, useJson } from "@/components/ui";

type Data = {
  available: boolean;
  signals: {
    id: number; source: string; event_type: string; params_json: string;
    evidence: string; backend: string; prompt_version: string;
    confidence: number; status: string; created_at: string;
  }[];
  log: { ts: string; agent: string; action: string; detail: string;
         outcome: string }[];
  agenticProduction: number | null;
  validation: { check_name: string; status: string }[];
};

const statusStyle: Record<string, string> = {
  approved: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  pending: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  rejected: "bg-rose-100 text-rose-900 dark:bg-rose-950 dark:text-rose-200",
};

export default function SignalsPage() {
  const d = useJson<Data>("/api/signals");

  if (d && !d.available) {
    return (
      <div className="max-w-2xl">
        <h1 className="text-xl font-semibold mb-2">Signals & agent log</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          No signals have been extracted yet. Run{" "}
          <code className="font-mono">python engine/run_pipeline.py --signals</code>{" "}
          to scan the inbox, approve with{" "}
          <code className="font-mono">--approve-signals</code>, then{" "}
          <code className="font-mono">--agents</code> for the planning loop —
          and refresh this page.
        </p>
      </div>
    );
  }

  const approved = d?.signals.filter((s) => s.status === "approved").length ?? 0;
  const pending = d?.signals.filter((s) => s.status === "pending").length ?? 0;

  return (
    <div>
      <h1 className="text-xl font-semibold mb-1">Signals & agent log</h1>
      <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-5 max-w-2xl">
        Unstructured inbox messages become typed, auditable planning events.
        Nothing touches a plan until a human approves it; the agentic loop
        below records every handoff.
      </p>

      <div className="grid gap-3 sm:grid-cols-4 mb-6">
        <Stat label="events extracted" value={`${d?.signals.length ?? "–"}`} />
        <Stat label="approved / pending" value={`${approved} / ${pending}`} />
        <Stat
          label="agentic plan production"
          value={d?.agenticProduction ? `${fmt(d.agenticProduction)} u` : "not published"}
        />
        <Stat
          label="agentic validators"
          value={
            d?.validation.length
              ? `${d.validation.filter((v) => v.status === "PASS").length}/${d.validation.length} PASS`
              : "–"
          }
        />
      </div>

      <Card
        title="Extracted events"
        note="Every event carries provenance: source, verbatim evidence quote, backend, prompt version, confidence. Approve/reject via the CLI (--approve-signals / --reject-signals); decisions survive re-extraction."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wide text-zinc-500">
                <th className="py-1.5 pr-3">Source</th>
                <th className="pr-3">Type</th>
                <th className="pr-3">Parameters</th>
                <th className="pr-3">Evidence</th>
                <th className="pr-3">Backend</th>
                <th className="pr-3 text-right">Conf</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {(d?.signals ?? []).map((s) => (
                <tr key={s.id} className="border-t border-zinc-200 dark:border-zinc-800 align-top">
                  <td className="py-1.5 pr-3 font-mono text-[11px] whitespace-nowrap">{s.source}</td>
                  <td className="pr-3 whitespace-nowrap">{s.event_type}</td>
                  <td className="pr-3 font-mono text-[11px]">{s.params_json}</td>
                  <td className="pr-3 text-zinc-500 dark:text-zinc-400 max-w-72">
                    “{s.evidence.slice(0, 140)}{s.evidence.length > 140 ? "…" : ""}”
                  </td>
                  <td className="pr-3 font-mono text-[11px] whitespace-nowrap">
                    {s.backend} · {s.prompt_version}
                  </td>
                  <td className="pr-3 text-right tabular-nums">{s.confidence.toFixed(2)}</td>
                  <td>
                    <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${statusStyle[s.status] ?? ""}`}>
                      {s.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card
        title="Agent log"
        note="Append-only audit trail of the planning loop: who did what, and what the verifier decided. REJECTED lines carry the exact reason."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wide text-zinc-500">
                <th className="py-1.5 pr-3">Time (UTC)</th>
                <th className="pr-3">Agent</th>
                <th className="pr-3">Action</th>
                <th className="pr-3">Detail</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              {(d?.log ?? []).map((l, i) => (
                <tr key={i} className="border-t border-zinc-200 dark:border-zinc-800 align-top">
                  <td className="py-1.5 pr-3 font-mono text-[11px] whitespace-nowrap">
                    {l.ts.replace("T", " ").replace("+00:00", "")}
                  </td>
                  <td className="pr-3 whitespace-nowrap font-medium">{l.agent}</td>
                  <td className="pr-3 whitespace-nowrap">{l.action}</td>
                  <td className="pr-3 text-zinc-600 dark:text-zinc-400">{l.detail}</td>
                  <td className={`whitespace-nowrap font-medium ${
                    l.outcome.includes("REJECT") ? "text-rose-600 dark:text-rose-400"
                    : l.outcome.includes("ACCEPT") || l.outcome === "DONE"
                      ? "text-emerald-700 dark:text-emerald-400"
                      : "text-zinc-500"}`}>
                    {l.outcome}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
