import { spawnSync } from "child_process";
import fs from "fs";
import path from "path";
import { NextRequest, NextResponse } from "next/server";
import {
  crossOriginBlock,
  ENGINE_DIR,
  INBOX_DIR,
  isSafeInboxName,
  labeledFixtures,
  writeDb,
} from "@/lib/mutate";

// The signals inbox over HTTP — the create/delete surface (docs D31).
//
// GET    lists inbox files with per-file event counts and a `protected`
//        flag (labels.json fixtures are the eval ground truth: immutable).
// POST   {text, filename?, extract?} writes a NEW .txt message, optionally
//        running real extraction (engine/extract_only.py — the same
//        extract_inbox the CLI runs, minus the eval pass). Text only:
//        images arrive by dropping files into engine/signals_inbox/.
// DELETE {filename} removes an unprotected file plus its PENDING rows.
//        Approved/rejected rows survive on purpose — they are the audit
//        trail, and rejections must outlive their source (content-hash
//        keyed) so a deleted-and-re-added message can't dodge a rejection.

const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif"]);

export function GET() {
  const prot = labeledFixtures();
  const counts = new Map<string, Record<string, number>>();
  try {
    for (const r of writeDb()
      .prepare(
        "SELECT source, status, COUNT(*) AS n FROM signals GROUP BY source, status"
      )
      .all() as { source: string; status: string; n: number }[]) {
      const c = counts.get(r.source) ?? {};
      c[r.status] = r.n;
      counts.set(r.source, c);
    }
  } catch {
    // signals table may not exist yet — file list still works
  }
  const files = fs
    .readdirSync(INBOX_DIR)
    .filter((n) => n.endsWith(".txt") || IMAGE_EXTS.has(path.extname(n).toLowerCase()))
    .sort()
    .map((name) => ({
      name,
      kind: name.endsWith(".txt") ? "text" : "image",
      bytes: fs.statSync(path.join(INBOX_DIR, name)).size,
      protected: prot.has(name),
      events: counts.get(name) ?? {},
    }));
  return NextResponse.json({ files, hasKey: Boolean(process.env.ANTHROPIC_API_KEY) });
}

function runExtraction(): { ran: boolean; summary?: unknown; error?: string } {
  const attempts: string[][] = [
    ["conda", "run", "-n", "avathon", "--no-capture-output", "python", "extract_only.py"],
    ["python", "extract_only.py"],
  ];
  let lastErr = "";
  for (const [cmd, ...args] of attempts) {
    const r = spawnSync(cmd, args, {
      cwd: ENGINE_DIR,
      timeout: 180_000,
      encoding: "utf-8",
      shell: true, // conda is a .bat on Windows
    });
    if (r.status === 0 && r.stdout) {
      try {
        const line = r.stdout.trim().split(/\r?\n/).pop() ?? "";
        return { ran: true, summary: JSON.parse(line) };
      } catch {
        return { ran: true, summary: r.stdout.trim().slice(-400) };
      }
    }
    lastErr = (r.stderr || r.stdout || String(r.error ?? "spawn failed")).slice(-400);
  }
  return {
    ran: false,
    error:
      `extraction could not run from the UI (${lastErr.trim()}). ` +
      "The message file is saved — run: python engine/run_pipeline.py --signals",
  };
}

export async function POST(req: NextRequest) {
  const blocked = crossOriginBlock(req);
  if (blocked) return NextResponse.json({ ok: false, error: blocked }, { status: 403 });
  let body: { text?: string; filename?: string; extract?: boolean };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid JSON" }, { status: 400 });
  }
  const text = (body.text ?? "").trim();
  if (!text || text.length > 4000) {
    return NextResponse.json(
      { ok: false, error: "text is required (max 4000 chars)" },
      { status: 400 }
    );
  }
  const filename = body.filename?.trim() || `ui_note_${Date.now()}.txt`;
  if (!isSafeInboxName(filename) || !filename.endsWith(".txt")) {
    return NextResponse.json(
      { ok: false, error: "filename must be a plain name ending in .txt" },
      { status: 400 }
    );
  }
  if (labeledFixtures().has(filename)) {
    return NextResponse.json(
      { ok: false, error: `${filename} is an eval fixture — pick another name` },
      { status: 403 }
    );
  }
  const full = path.join(INBOX_DIR, filename);
  if (fs.existsSync(full)) {
    return NextResponse.json(
      { ok: false, error: `${filename} already exists` },
      { status: 409 }
    );
  }
  fs.writeFileSync(full, text + "\n", "utf-8");
  const extraction = body.extract ? runExtraction() : { ran: false };
  return NextResponse.json({ ok: true, filename, extraction });
}

export async function DELETE(req: NextRequest) {
  const blocked = crossOriginBlock(req);
  if (blocked) return NextResponse.json({ ok: false, error: blocked }, { status: 403 });
  let body: { filename?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid JSON" }, { status: 400 });
  }
  const filename = body.filename ?? "";
  if (!isSafeInboxName(filename)) {
    return NextResponse.json({ ok: false, error: "invalid filename" }, { status: 400 });
  }
  if (labeledFixtures().has(filename)) {
    return NextResponse.json(
      {
        ok: false,
        error:
          `${filename} is a labeled eval fixture — deleting it would break ` +
          "the extraction-quality harness (labels.json). It stays.",
      },
      { status: 403 }
    );
  }
  const full = path.join(INBOX_DIR, filename);
  if (!fs.existsSync(full)) {
    return NextResponse.json({ ok: false, error: "no such inbox file" }, { status: 404 });
  }
  fs.unlinkSync(full);
  let removedPending = 0;
  try {
    removedPending = writeDb()
      .prepare("DELETE FROM signals WHERE source = ? AND status = 'pending'")
      .run(filename).changes;
  } catch {
    // no signals table yet — nothing to prune
  }
  return NextResponse.json({
    ok: true,
    removedPending,
    note: "approved/rejected rows are kept — they are the audit trail",
  });
}
