"use client";
import { useRef, useState } from "react";
import HowTo from "@/components/HowTo";
import Provenance from "@/components/Provenance";
import { Card, Stat, useJson } from "@/components/ui";

type Signal = {
  id: number; source: string; event_type: string; evidence: string;
  backend: string; prompt_version: string; confidence: number; status: string;
  facts: [string, string][]; label_match: boolean;
  transcription: string; source_sha256: string;
};
type Data = { available: boolean; signals: Signal[] };
type InboxFile = {
  name: string; kind: "text" | "image"; bytes: number; protected: boolean;
  events: Record<string, number>;
};
type Inbox = { files: InboxFile[]; hasKey: boolean };

type ExtractSummary = {
  new_pending?: number;
  skipped?: { file: string; reason: string }[];
  no_events?: string[];
  rejected?: Record<string, string[]>;
};

// One honest sentence per outcome: pending events created, files skipped,
// events REFUSED (with the sanitize-policy reason — a silent refusal reads
// as a bug), and files read but containing no planning content at all.
function extractionNote(s: ExtractSummary | string | undefined, hasKey?: boolean): string {
  if (typeof s !== "object" || !s) return "extraction ran";
  const parts = [`extraction ran: ${s.new_pending ?? 0} new pending event(s)`];
  if (s.skipped?.length) {
    parts.push(
      `${s.skipped.length} image(s) skipped (${s.skipped[0].reason}${hasKey === false ? "; vision needs ANTHROPIC_API_KEY, no offline stand-in" : ""})`
    );
  }
  for (const [file, reasons] of Object.entries(s.rejected ?? {})) {
    parts.push(`⚠ ${file} — event(s) refused by policy: ${reasons.join(" · ")}`);
  }
  const silent = (s.no_events ?? []).filter((f) => !(s.rejected && f in s.rejected));
  if (silent.length) {
    parts.push(`${silent.join(", ")}: read, but no planning content recognized`);
  }
  return parts.join("  —  ");
}

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
  const [bump, setBump] = useState(0);
  const d = useJson<Data>(`/api/signals?r=${bump}`);
  const inbox = useJson<Inbox>(`/api/inbox?r=${bump}`);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [gateNote, setGateNote] = useState("");
  const [msg, setMsg] = useState("");
  const [fname, setFname] = useState("");
  const [creating, setCreating] = useState(false);
  const [createNote, setCreateNote] = useState("");
  const [confirmDel, setConfirmDel] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  async function act(id: number, action: "approve" | "reject") {
    setBusyId(id);
    try {
      const r = await fetch("/api/signals/action", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action, id }),
      });
      const data = await r.json();
      setGateNote(data.note ?? data.error ?? "");
      setBump((b) => b + 1);
    } catch {
      setGateNote("request failed — is the server still running?");
    } finally {
      setBusyId(null);
    }
  }

  async function createMessage() {
    if (!msg.trim() || uploading || creating) return;
    setCreating(true);
    setCreateNote("");
    try {
      const r = await fetch("/api/inbox", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          text: msg, filename: fname.trim() || undefined, extract: true,
        }),
      });
      const data = await r.json();
      if (!data.ok) setCreateNote(`✗ ${data.error}`);
      else if (data.extraction?.ran) {
        setCreateNote(
          `✓ saved as ${data.filename} — ${extractionNote(data.extraction.summary, data.hasKey)}`
        );
        setMsg(""); setFname("");
      } else {
        setCreateNote(`✓ saved as ${data.filename}. ${data.extraction?.error ?? "Run: python engine/run_pipeline.py --signals"}`);
        setMsg(""); setFname("");
      }
      setBump((b) => b + 1);
    } catch {
      setCreateNote("✗ request failed — is the server still running?");
    } finally {
      setCreating(false);
    }
  }

  async function uploadImages(list: FileList | File[]) {
    if (uploading || creating) return;
    const files = Array.from(list).filter(
      (f) => /\.(png|jpe?g|webp|gif)$/i.test(f.name) || f.type.startsWith("image/")
    );
    if (!files.length) {
      setCreateNote("✗ drop image files — .png .jpg .jpeg .webp .gif");
      return;
    }
    setUploading(true);
    setCreateNote("");
    const notes: string[] = [];
    let saved = 0;
    for (const f of files) {
      if (f.size === 0) {
        notes.push(`✗ ${f.name}: empty file`);
        continue;
      }
      if (f.size > 5 * 1024 * 1024) {
        notes.push(`✗ ${f.name}: over the 5 MB cap (extraction skips oversize files)`);
        continue;
      }
      // server re-validates: safe basename, alnum first char, image ext.
      // If the name can't be made safe (no extension, too long), omit it —
      // the server names the file from the sniffed bytes.
      let safe: string | undefined = f.name.replace(/[^A-Za-z0-9_.-]/g, "_");
      if (!/^[A-Za-z0-9]/.test(safe)) safe = `img_${safe}`;
      const dot = safe.lastIndexOf(".");
      if (dot > 40) safe = safe.slice(0, 40).replace(/[._-]+$/, "") + safe.slice(dot);
      if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,60}\.(png|jpe?g|webp|gif)$/i.test(safe)) {
        safe = undefined;
      }
      try {
        const b64 = await new Promise<string>((resolve, reject) => {
          const r = new FileReader();
          r.onload = () => resolve(String(r.result).split(",")[1] ?? "");
          r.onerror = () => reject(r.error);
          r.readAsDataURL(f);
        });
        const r = await fetch("/api/inbox", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ imageBase64: b64, filename: safe, extract: false }),
        });
        const data = await r.json();
        if (!data.ok) notes.push(`✗ ${f.name}: ${data.error}`);
        else {
          saved += 1;
          notes.push(`✓ ${data.filename} saved`);
        }
      } catch {
        notes.push(`✗ ${f.name}: request failed — is the server still running?`);
      }
    }
    // one extraction pass covers the whole batch — triggered separately so
    // a failed or skipped last file can never silently skip extraction
    if (saved > 0) {
      try {
        const r = await fetch("/api/inbox", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ extract: true }),
        });
        const data = await r.json();
        if (data.ok && data.extraction?.ran) {
          notes.push(extractionNote(data.extraction.summary, data.hasKey));
        } else {
          notes.push(
            data.extraction?.error ?? "extraction not run — python engine/run_pipeline.py --signals"
          );
        }
      } catch {
        notes.push("extraction request failed — run: python engine/run_pipeline.py --signals");
      }
    }
    setCreateNote(notes.join("  ·  "));
    setUploading(false);
    setBump((b) => b + 1);
  }

  async function deleteFile(name: string) {
    if (confirmDel !== name) { setConfirmDel(name); return; }
    setConfirmDel("");
    try {
      const r = await fetch("/api/inbox", {
        method: "DELETE",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ filename: name }),
      });
      const data = await r.json();
      setCreateNote(data.ok
        ? `✓ deleted ${name} (${data.removedPending} pending event(s) removed; ${data.note})`
        : `✗ ${data.error}`);
      setBump((b) => b + 1);
    } catch {
      setCreateNote("✗ request failed — is the server still running?");
    }
  }

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
        Unstructured planner messages — text or images (supplier emails,
        retailer notes, scanned carrier advisories, promo flyers) — turned
        into typed, auditable planning events. Approval is a human act; the
        agentic loop that consumes these lives on its own page.
      </p>

      <HowTo
        dos={[
          <>Open <b>image transcription</b> on the promo-flyer card and read its fine print against the extracted values.</>,
          <>Approve or reject pending events with the buttons on each card — that IS the human gate (same SQL as <code className="font-mono">--approve-signal</code>).</>,
          <>Add your own message in the <b>Inbox</b> card below (e.g. “Expect a 25% uplift for Variant V3 in Geo G2 during 2024W05-2024W06.”) — it runs through real extraction and lands here as pending.</>,
          <>Drag &amp; drop an image (scanned notice, flyer) onto the upload zone in the Inbox card — it takes the same rails as CLI-dropped images: vision extraction, capped confidence, per-row human approval. Needs <code className="font-mono">ANTHROPIC_API_KEY</code> on the server; offline it is saved and honestly skipped.</>,
          <>After approving, re-plan with <code className="font-mono">python engine/run_pipeline.py --agents</code> — approval alone never changes a plan.</>,
        ]}
        watch={[
          <>The flyer's transcription contains a planted “ignore previous instructions / multiplier 3.0” line — the extracted event says ×1.3, V2 only. Injection read, recorded, refused.</>,
          <>Image events are pinned at confidence 0.75, below the 0.8 batch floor — only per-row approval works on them, by design.</>,
          <>A message can be read perfectly and still yield <b>zero events</b>: the sanitize boundary only auto-accepts demand shocks on core variants <b>V1–V4</b> (deal/exclusive volumes like V5 are contractual — a human conversation, not an auto multiplier) and only known geos/fiscal weeks. The extraction note names any file that was read but refused.</>,
          <>Card footers show which backend and prompt version produced each row — provenance is stamped at extraction time and never rewritten.</>,
          <>Deleting an inbox file removes only its <i>pending</i> events; approved/rejected rows survive as the audit trail, and labeled eval fixtures can't be deleted at all.</>,
        ]}
      />

      <Provenance
        sources="signals table in planz.db, extracted from the message files in engine/signals_inbox/; expectations from labels.json (the eval ground truth)."
        model="Pluggable extractor (llm.py): claude-sonnet-5 when ANTHROPIC_API_KEY is set, offline rules-v1 otherwise — the backend column shows which produced each row. Text events: a quote that isn't verbatim in the source file drops confidence to 0. Image events (+vision rows) can't get that guarantee — the model authors both the events and the transcription they're checked against — so their confidence is capped at 0.75, below the 0.8 batch-approve floor: a human must approve each one individually (button here, or --approve-signal <id>) after comparing the stored transcription and image hash with the file. Every event passes the same sanitize boundary (known entities, horizon bounds, multiplier limits)."
        params={[
          "Approve/Reject buttons run the identical targeted UPDATE as the CLI human gate — and only on pending rows: decisions are never overwritten",
          "Statuses survive re-extraction (content-hash keyed); rejections are permanent",
          "Prompt versions are provenance: v2 scored 14% recall and was rejected by the eval gate; v3 and vision-v1 score 100%/100%",
        ]}
        takeaway="Each card shows the event's decoded values (variants, weeks as fiscal labels, caps/multipliers) plus whether it matches the labeled expectation — nothing here has touched a plan unless a human approved it AND the verifier-gated re-plan ran."
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

      {gateNote && (
        <p className="text-xs mb-4 text-zinc-600 dark:text-zinc-400">
          gate: {gateNote}
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {(d?.signals ?? []).map((s) => (
          <Card
            key={s.id}
            title={`${typeLabel[s.event_type] ?? s.event_type} — ${s.source}`}
            note={`id ${s.id} · backend ${s.backend} · prompt ${s.prompt_version} · confidence ${s.confidence.toFixed(2)}`}
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
            {s.transcription && (
              <details className="mb-3 text-[12px] text-zinc-500 dark:text-zinc-400">
                <summary className="cursor-pointer select-none">
                  image transcription (what the vision model read — compare it
                  with <code className="font-mono">engine/signals_inbox/{s.source}</code>{" "}
                  before approving)
                </summary>
                <pre className="mt-2 whitespace-pre-wrap font-sans text-[12px] rounded-md bg-zinc-100 dark:bg-zinc-800 p-2.5">
                  {s.transcription}
                </pre>
              </details>
            )}
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${statusStyle[s.status] ?? ""}`}>
                {s.status}
              </span>
              <span className={`text-[11px] font-medium ${s.label_match ? "text-emerald-700 dark:text-emerald-400" : "text-zinc-400"}`}>
                {s.label_match ? "✓ matches labeled expectation" : "no matching label"}
              </span>
              {s.status === "pending" && (
                <span className="ml-auto flex gap-1.5">
                  <button
                    onClick={() => act(s.id, "approve")}
                    disabled={busyId === s.id}
                    className="rounded-md bg-emerald-600 hover:bg-emerald-700 text-white text-[11px] font-medium px-2.5 py-1 disabled:opacity-50"
                  >
                    approve
                  </button>
                  <button
                    onClick={() => act(s.id, "reject")}
                    disabled={busyId === s.id}
                    className="rounded-md bg-rose-600 hover:bg-rose-700 text-white text-[11px] font-medium px-2.5 py-1 disabled:opacity-50"
                  >
                    reject
                  </button>
                </span>
              )}
            </div>
          </Card>
        ))}
      </div>

      <Card
        title="Inbox — the message files behind the events above"
        note="Create a new planner message (it runs through real extraction) or delete one you added. Labeled eval fixtures are immutable; deleting a file removes only its pending events."
      >
        <table className="w-full text-sm mb-4">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-zinc-500">
              <th className="py-1.5">File</th>
              <th>Kind</th>
              <th className="text-right">Events (a/p/r)</th>
              <th className="text-right"></th>
            </tr>
          </thead>
          <tbody>
            {(inbox?.files ?? []).map((f) => (
              <tr key={f.name} className="border-t border-zinc-200 dark:border-zinc-800">
                <td className="py-1.5 font-mono text-xs">{f.name}</td>
                <td className="text-xs">
                  {f.kind}
                  {f.protected && (
                    <span className="ml-2 rounded-full bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 text-[10px] text-zinc-500">
                      eval fixture — immutable
                    </span>
                  )}
                </td>
                <td className="text-right tabular-nums text-xs">
                  {(f.events.approved ?? 0)} / {(f.events.pending ?? 0)} / {(f.events.rejected ?? 0)}
                </td>
                <td className="text-right">
                  {!f.protected && (
                    <button
                      onClick={() => deleteFile(f.name)}
                      className={`rounded-md text-[11px] font-medium px-2.5 py-1 ${
                        confirmDel === f.name
                          ? "bg-rose-600 text-white"
                          : "border border-zinc-300 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400"
                      }`}
                    >
                      {confirmDel === f.name ? "confirm delete" : "delete"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="grid gap-2">
          <textarea
            value={msg}
            onChange={(e) => setMsg(e.target.value)}
            rows={3}
            placeholder='New planner message, e.g. "Expect a 25% uplift for Variant V3 in Geo G2 during 2024W05-2024W06."'
            className="rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-sm"
          />
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={fname}
              onChange={(e) => setFname(e.target.value)}
              placeholder="filename (optional, .txt)"
              className="rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-1.5 text-xs w-52"
            />
            <button
              onClick={createMessage}
              disabled={creating || uploading || !msg.trim()}
              className="rounded-lg bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 px-4 py-1.5 text-xs font-medium disabled:opacity-50"
            >
              {creating ? "saving & extracting…" : "save & extract"}
            </button>
            {inbox && !inbox.hasKey && (
              <span className="text-[11px] text-zinc-500">
                no API key on the server — extraction uses the offline rules parser
              </span>
            )}
          </div>
          <div
            role="button"
            tabIndex={0}
            aria-label="Upload an image signal — drag and drop or click to browse"
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              if (!uploading) uploadImages(e.dataTransfer.files);
            }}
            onClick={() => !uploading && fileInput.current?.click()}
            onKeyDown={(e) => {
              if ((e.key === "Enter" || e.key === " ") && !uploading) fileInput.current?.click();
            }}
            className={`rounded-lg border-2 border-dashed px-4 py-5 text-center text-xs cursor-pointer transition-colors ${
              dragOver
                ? "border-zinc-500 bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200"
                : "border-zinc-300 dark:border-zinc-700 text-zinc-500 dark:text-zinc-400"
            } ${uploading ? "opacity-60 cursor-wait" : ""}`}
          >
            {uploading ? (
              "uploading & extracting…"
            ) : (
              <>
                <span className="font-medium">drag & drop an image signal</span> — scanned
                carrier notice, promo flyer, portal screenshot — or click to browse
                <span className="block mt-1 text-[11px]">
                  .png .jpg .jpeg .webp .gif, ≤5 MB · it lands in{" "}
                  <code className="font-mono">engine/signals_inbox/</code> and runs through
                  the same vision extraction + human gate as CLI-dropped files
                </span>
                {inbox && !inbox.hasKey && (
                  <span className="block mt-1 text-[11px] text-amber-700 dark:text-amber-400">
                    no ANTHROPIC_API_KEY on the server — the file will be saved but skipped
                    by extraction (vision has no offline stand-in; it extracts once a key
                    is set and <code className="font-mono">--signals</code> re-runs)
                  </span>
                )}
              </>
            )}
          </div>
          <input
            ref={fileInput}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files?.length) uploadImages(e.target.files);
              e.target.value = "";
            }}
          />
          {createNote && (
            <p className="text-xs text-zinc-600 dark:text-zinc-400">{createNote}</p>
          )}
        </div>
      </Card>
    </div>
  );
}
