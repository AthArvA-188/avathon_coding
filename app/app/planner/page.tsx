"use client";
import { useEffect, useRef, useState } from "react";
import Provenance from "@/components/Provenance";
import { Card } from "@/components/ui";

type AskResponse = {
  parser: string;
  intent: Record<string, unknown>;
  mode: "deterministic" | "action";
  answer: string;
  table: Record<string, unknown>[];
  sql: string[];
  action: {
    proposed_event: Record<string, unknown>;
    how_to_apply: string[];
  } | null;
};

const EXAMPLES = [
  "What is production for V3 in Q4 under the scenario plan?",
  "Demand for V1 in G1 in 2024Q1",
  "WOS for V2 in G1",
  "Freight breakdown for the baseline plan",
  "Stockouts in the heuristic plan",
  "Compare baseline vs scenario",
  "Why did the scenario change V2?",
  "What if Retailer R4 doubles their Q4 order on V3?",
];

export default function PlannerPage() {
  const [question, setQuestion] = useState("");
  const [listening, setListening] = useState(false);
  const [speak, setSpeak] = useState(true);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<AskResponse | null>(null);
  const [voiceOk, setVoiceOk] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recRef = useRef<any>(null);

  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SR = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;
    if (!SR) return;
    setVoiceOk(true);
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.onresult = (e: { results: { [i: number]: { [j: number]: { transcript: string } } } }) => {
      const text = e.results[0][0].transcript;
      setQuestion(text);
      void ask(text);
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function ask(q: string) {
    if (!q.trim()) return;
    setBusy(true);
    setRes(null);
    try {
      const r = await fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      const data = (await r.json()) as AskResponse;
      setRes(data);
      if (speak && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(data.answer));
      }
    } finally {
      setBusy(false);
    }
  }

  const cols = res?.table?.length ? Object.keys(res.table[0]) : [];

  return (
    <div>
      <h1 className="text-xl font-semibold mb-1">Ask the planner</h1>
      <p className="text-sm text-zinc-500 dark:text-zinc-400 mb-4 max-w-2xl">
        Speak or type a planning question. Data questions are answered
        deterministically from the database (the SQL is shown); what-if
        questions become structured events for the gated signals flow — the
        language layer can never change a plan directly.
      </p>

      <Provenance
        sources="planz.db plan tables (mps, shipments, inventory, forecast, calendar) — the same rows every other page reads."
        model="Intent parsing: Claude (claude-sonnet-5) when ANTHROPIC_API_KEY is set on the server, otherwise an offline rules parser — each response labels which one ran. Answers: whitelisted read-only SQL templates; the LLM never generates SQL or numbers."
        params={[
          "Voice in: Web Speech API (Chrome/Edge); voice out: speechSynthesis (toggle below)",
          "What-if guardrail: proposals become sanitize-checked events requiring --approve-signals",
          "Default plan: baseline (say 'scenario', 'heuristic' or 'agentic' to switch)",
        ]}
        takeaway="Deterministic math answers planning questions; language only translates intent and narrates — so a generated answer can never violate capacity or pack-out rules."
      />

      <div className="flex flex-wrap gap-3 items-center mb-3">
        <input
          className="flex-1 min-w-64 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2.5 text-sm"
          placeholder="e.g. What is production for V3 in Q4 under the scenario plan?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask(question)}
        />
        <button
          onClick={() => {
            if (!recRef.current) return;
            if (listening) { recRef.current.stop(); return; }
            setListening(true);
            recRef.current.start();
          }}
          disabled={!voiceOk}
          className={`rounded-lg px-4 py-2.5 text-sm font-medium border ${
            listening
              ? "bg-rose-600 text-white border-rose-600 animate-pulse"
              : "bg-white dark:bg-zinc-900 border-zinc-300 dark:border-zinc-700"
          } ${!voiceOk ? "opacity-40" : ""}`}
          title={voiceOk ? "Speak your question" : "Web Speech API not available in this browser"}
        >
          {listening ? "● listening…" : "🎤 speak"}
        </button>
        <button
          onClick={() => ask(question)}
          disabled={busy}
          className="rounded-lg bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-4 py-2.5 text-sm font-medium disabled:opacity-50"
        >
          {busy ? "thinking…" : "ask"}
        </button>
        <label className="flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400 cursor-pointer">
          <input type="checkbox" checked={speak} onChange={(e) => setSpeak(e.target.checked)} />
          speak answers
        </label>
      </div>

      <div className="flex flex-wrap gap-2 mb-6">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            onClick={() => { setQuestion(ex); void ask(ex); }}
            className="text-xs rounded-full border border-zinc-300 dark:border-zinc-700 px-3 py-1.5 text-zinc-600 dark:text-zinc-400 hover:border-zinc-500"
          >
            {ex}
          </button>
        ))}
      </div>

      {res && (
        <>
          <Card
            title={res.mode === "action" ? "Guarded what-if" : "Answer"}
            note={`intent parsed by ${res.parser} → ${JSON.stringify(res.intent)}`}
          >
            <p className="text-sm leading-6 max-w-3xl">{res.answer}</p>
            {res.action && (
              <div className="mt-3 text-sm">
                <div className="font-medium mb-1">Proposed structured event</div>
                <pre className="rounded-lg bg-zinc-900 text-zinc-100 p-3 text-xs overflow-x-auto">
{JSON.stringify(res.action.proposed_event, null, 2)}
                </pre>
                <div className="font-medium mt-3 mb-1">To apply it (human-gated)</div>
                <ol className="list-decimal pl-5 text-xs text-zinc-600 dark:text-zinc-400">
                  {res.action.how_to_apply.map((s) => <li key={s}>{s}</li>)}
                </ol>
              </div>
            )}
          </Card>

          {res.table.length > 0 && (
            <Card title="Data" note="Rows returned by the query below.">
              <div className="overflow-x-auto">
                <table className="w-full text-[12.5px]">
                  <thead>
                    <tr className="text-left text-[10px] uppercase tracking-wide text-zinc-500">
                      {cols.map((c) => <th key={c} className="py-1.5 pr-4">{c}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {res.table.slice(0, 60).map((r, i) => (
                      <tr key={i} className="border-t border-zinc-200 dark:border-zinc-800">
                        {cols.map((c) => (
                          <td key={c} className="py-1 pr-4 tabular-nums">
                            {typeof r[c] === "number"
                              ? (r[c] as number).toLocaleString("en-US")
                              : String(r[c])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {res.sql.length > 0 && (
            <Card title="Provenance" note="Exactly what ran against planz.db — nothing else did.">
              {res.sql.map((s) => (
                <pre key={s} className="rounded-lg bg-zinc-900 text-zinc-100 p-3 text-[11px] overflow-x-auto mb-2">{s}</pre>
              ))}
            </Card>
          )}
        </>
      )}
    </div>
  );
}
