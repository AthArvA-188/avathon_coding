export default function Home() {
  const cards = [
    {
      href: "/forecast",
      title: "Forecast",
      body: "52-week demand at SKU × geo × channel grain with P10–P90 bands, filterable, plus holdout accuracy vs baselines.",
    },
    {
      href: "/plan",
      title: "MPS & Pack-out",
      body: "Week-by-week production and pack-out slots, capacity utilization vs the 17,280/224,000 caps, freight mix, WOS trajectories.",
    },
    {
      href: "/scenario",
      title: "Shortage Scenario",
      body: "Toggle the V2+V4 enclosure shortage (4,500 u/wk, 6 weeks) and see the plan diff: allocation, deltas, recovery.",
    },
    {
      href: "/signals",
      title: "Signals",
      body: "LLM-extracted planning events with decoded values, provenance, eval-label matches, and the human approval gate.",
    },
    {
      href: "/agents",
      title: "Agents",
      body: "The agentic loop's append-only audit trail: proposals, verifier rejections with reasons, and the published plan.",
    },
    {
      href: "/planner",
      title: "Ask the Planner",
      body: "Voice or text questions answered deterministically from the database — with the SQL shown — and guarded what-ifs.",
    },
  ];
  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-semibold tracking-tight mb-2">
        Program Z planning workspace
      </h1>
      <p className="text-sm text-zinc-600 dark:text-zinc-400 mb-8 leading-6">
        Read-only views over <code className="font-mono">planz.db</code>, built
        by the Python pipeline (<code className="font-mono">ingest → forecast →
        MPS → scenario</code>). To re-plan with new inputs, re-run the pipeline
        and refresh.
      </p>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((c) => (
          <a
            key={c.href}
            href={c.href}
            className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 hover:border-zinc-400 dark:hover:border-zinc-600"
          >
            <div className="font-semibold mb-1.5">{c.title}</div>
            <div className="text-xs leading-5 text-zinc-600 dark:text-zinc-400">
              {c.body}
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
