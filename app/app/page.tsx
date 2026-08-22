import HowTo from "@/components/HowTo";

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
        Views over <code className="font-mono">planz.db</code>, built by the
        Python pipeline (<code className="font-mono">ingest → forecast → MPS →
        scenario</code>). Plan tables are read-only; the only writes are the
        human gate on the Signals page (approve / reject / inbox messages).
        Re-planning always goes through the verifier-gated pipeline.
      </p>
      <HowTo
        dos={[
          <>Walk the cards in order — they mirror the pipeline: forecast → plan → scenario, then the three AI prototypes.</>,
          <>On every page, open the two strips at the top: <b>How to use this page</b> and <b>Where these numbers come from</b>.</>,
          <>Signals & Agents need their stages run once: <code className="font-mono">--signals</code>, approve, <code className="font-mono">--agents</code>.</>,
        ]}
        watch={[
          <>The one-line story: demand 953k vs capacity 896k — everything downstream is about rationing a scarce factory.</>,
          <>The app never re-plans: it reads <code className="font-mono">planz.db</code>; only the Signals page writes (the human gate + inbox), and re-planning stays with the verifier-gated CLI.</>,
        ]}
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 mb-6">
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

      <details className="mb-4 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-sm open:pb-3">
        <summary className="cursor-pointer select-none px-4 py-2.5 font-medium text-zinc-700 dark:text-zinc-300">
          Before you start
        </summary>
        <ul className="px-4 pt-1 list-disc pl-9 text-[13px] leading-6 text-zinc-600 dark:text-zinc-400">
          <li>One command boots everything: <code className="font-mono">./start.ps1</code> (or <code className="font-mono">./start.sh</code>) — env, deps, full pipeline, UI. Pipeline already ran? <code className="font-mono">cd app &amp;&amp; npm run dev</code> is enough.</li>
          <li>Signals &amp; Agents need their stages once: <code className="font-mono">python engine/run_pipeline.py --signals</code>, approve on the Signals page (or <code className="font-mono">--approve-signals</code>), then <code className="font-mono">--agents</code>.</li>
          <li>Voice input needs Chrome or Edge (Web Speech API); typing works everywhere.</li>
          <li>Optional: set <code className="font-mono">ANTHROPIC_API_KEY</code> in the shell <i>before</i> starting the pipeline/UI to get claude-sonnet-5 extraction, image reading, and intent parsing. Without it, offline rule-based stand-ins take the same slots and label themselves honestly (images are skipped, never guessed at).</li>
          <li>Image signals can be dragged &amp; dropped straight onto the Signals page's upload zone (≤5 MB png/jpg/webp/gif). High/low-case plans: <code className="font-mono">python engine/run_pipeline.py --mps --quantile p90</code> (or p10), then pick <code className="font-mono">baseline_p90</code> in the Plan page's plan picker.</li>
        </ul>
      </details>

      <details className="mb-4 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-sm open:pb-3">
        <summary className="cursor-pointer select-none px-4 py-2.5 font-medium text-zinc-700 dark:text-zinc-300">
          The 60-second demo script
        </summary>
        <ol className="px-4 pt-1 list-decimal pl-9 text-[13px] leading-6 text-zinc-600 dark:text-zinc-400">
          <li><b>MPS &amp; Pack-out:</b> “Demand is 953k, capacity is 896k — three quarters run at exactly the cap, and the $4.7M of air freight is what scarcity costs.”</li>
          <li><b>Scenario toggle:</b> “A 6-week summer parts shortage costs almost no volume — but the recovery curve doesn't close until the following April (2024W29). Time, not units, is the damage.”</li>
          <li><b>Signals, promo-flyer card:</b> “This event came out of a <i>picture</i>. Open the transcription — there's a prompt injection in the fine print, and you can watch it get refused.”</li>
          <li><b>Ask the Planner, by voice:</b> ask about air freight, point at the SQL under the answer: “the model picks the question, the database answers it.”</li>
        </ol>
      </details>

      <details className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-sm open:pb-3">
        <summary className="cursor-pointer select-none px-4 py-2.5 font-medium text-zinc-700 dark:text-zinc-300">
          If something looks wrong
        </summary>
        <ul className="px-4 pt-1 list-disc pl-9 text-[13px] leading-6 text-zinc-600 dark:text-zinc-400">
          <li><b>Port 3000 busy:</b> an older dev server is alive — kill it or <code className="font-mono">npm run dev -- -p 3001</code>.</li>
          <li><b>Signals/Agents page says “run --signals”:</b> those stages are explicit-only — run them once (see above).</li>
          <li><b>Mic greyed out on /planner:</b> the browser lacks the Web Speech API — Chrome/Edge, or type. The browser may hand audio to its vendor's speech service; audio never touches this app's backend.</li>
          <li><b>Planner shows parser: rules</b> — no <code className="font-mono">ANTHROPIC_API_KEY</code> in the shell that started the UI; the regex parser still covers the example chips.</li>
          <li><b>Image signals missing/skipped:</b> vision needs the key at <code className="font-mono">--signals</code> time; offline they're skipped honestly.</li>
          <li><b>A number looks off:</b> <code className="font-mono">python engine/verify.py</code> — 14 independent checks sharing no code with the pipeline. If it passes and a page disagrees, that's a bug worth reporting.</li>
        </ul>
      </details>
    </div>
  );
}
