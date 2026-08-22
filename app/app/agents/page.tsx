"use client";
import Provenance from "@/components/Provenance";
import { Card, fmt, Stat, useJson } from "@/components/ui";

type Data = {
  available: boolean;
  log: { ts: string; agent: string; action: string; detail: string; outcome: string }[];
  agenticProduction: number | null;
  baselineProduction: number | null;
  unmet: number | null;
  validation: { check_name: string; status: string }[];
};

export default function AgentsPage() {
  const d = useJson<Data>("/api/agents");

  if (d && !d.available) {
    return (
      <div className="max-w-2xl">
        <h1 className="text-xl font-semibold mb-2">Agentic planning loop</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          The loop hasn&apos;t run yet. After extracting and approving signals, run{" "}
          <code className="font-mono">python engine/run_pipeline.py --agents</code>{" "}
          and refresh.
        </p>
      </div>
    );
  }

  const delta =
    d?.agenticProduction != null && d?.baselineProduction != null
      ? d.agenticProduction - d.baselineProduction
      : null;

  return (
    <div>
      <h1 className="text-xl font-semibold mb-1">Agentic planning loop</h1>
      <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-4 max-w-2xl">
        Six roles with bounded authority: signals are proposed, a human
        approves, the planner proposes greedy-first, and an independent
        verifier accepts or rejects with the reason attached. Every handoff
        lands in this append-only log.
      </p>

      <Provenance
        sources="agent_log table (append-only, spans runs) + plan tables under plan_id 'agentic'; signals come from the Signals page's table."
        model="Orchestrated loop over the existing engines: greedy heuristic proposal first, escalation to the PuLP/CBC MILP on rejection. VerifierAgent = the 9 independent constraint checks (validate.py) + a service policy computed from persisted inventory rows — never from planner self-reports."
        params={[
          "Service policy: unmet demand ≤ 0.5% of (shock-adjusted) forecast demand",
          "Demand-delta guard: shocks moving aggregate demand >15% always require human sign-off",
          "Human gate closed by default: --approve-signals or explicit --auto-approve",
          "Candidates staged as 'agentic_candidate'; promoted only on acceptance",
        ]}
        takeaway="The published agentic plan absorbed the approved signal events with the verifier's proof attached; rejected proposals (and why) stay visible below."
      />

      <div className="grid gap-3 sm:grid-cols-4 mb-6">
        <Stat
          label="published agentic plan"
          value={d?.agenticProduction ? `${fmt(d.agenticProduction)} u` : "not published"}
          sub={delta != null ? `${delta >= 0 ? "+" : ""}${fmt(delta)} vs baseline` : undefined}
        />
        <Stat label="unmet demand" value={d?.unmet != null ? `${fmt(d.unmet)} u` : "–"} />
        <Stat
          label="validators on the accepted plan"
          value={
            d?.validation.length
              ? `${d.validation.filter((v) => v.status === "PASS").length}/${d.validation.length} PASS`
              : "–"
          }
        />
        <Stat label="log entries (all runs)" value={`${d?.log.length ?? "–"}`} />
      </div>

      <Card
        title="Audit trail"
        note="Append-only across runs — approvals, rejections (with reasons), escalations, and publications are all reconstructable."
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
                    l.outcome.includes("REJECT") || l.outcome.includes("FAILED")
                      ? "text-rose-600 dark:text-rose-400"
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
