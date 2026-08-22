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
// POST   {text, filename?, extract?} writes a NEW .txt message, or
//        {imageBase64, filename?, extract?} a NEW image signal — base64
//        inside JSON, NOT multipart/form-data: multipart is a CSRF
//        "simple request" a hostile page could send without a preflight,
//        and the round-5 fix leans on requiring application/json. Bytes
//        are magic-sniffed (png/jpg/webp/gif), capped at 5 MB (mirrors
//        llm.MAX_IMAGE_BYTES), and the extension must match the bytes.
//        Either kind can then run real extraction (engine/extract_only.py
//        — the same extract_inbox the CLI runs, minus the eval pass), and
//        {extract: true} alone re-runs extraction with no new file (the
//        drop zone's one-pass-per-batch trigger).
// DELETE {filename} removes an unprotected file plus its PENDING rows.
//        Approved/rejected rows survive on purpose — they are the audit
//        trail, and rejections must outlive their source (content-hash
//        keyed) so a deleted-and-re-added message can't dodge a rejection.

const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif"]);

// mirrors engine/planz/llm.py MAX_IMAGE_BYTES — extraction skips oversize
// files anyway, so refuse them at the door with a reason instead
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

// The engine picks the vision API media type from the file EXTENSION, so
// the bytes must actually be what the name claims — a text file dressed as
// .png is exactly the smuggling this inbox should refuse.
const PNG_SIG = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
function sniffedExt(buf: Buffer): ".png" | ".jpg" | ".webp" | ".gif" | null {
  if (buf.length >= 8 && PNG_SIG.every((b, i) => buf[i] === b)) return ".png";
  if (buf.length >= 3 && buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return ".jpg";
  if (buf.length >= 12 && buf.toString("ascii", 0, 4) === "RIFF" && buf.toString("ascii", 8, 12) === "WEBP") return ".webp";
  if (buf.length >= 6 && ["GIF87a", "GIF89a"].includes(buf.toString("ascii", 0, 6))) return ".gif";
  return null;
}

function canonicalExt(name: string): string {
  const e = path.extname(name).toLowerCase();
  return e === ".jpeg" ? ".jpg" : e;
}

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
  let body: { text?: string; imageBase64?: string; filename?: string; extract?: boolean };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid JSON" }, { status: 400 });
  }
  const text = (body.text ?? "").trim();
  // tolerate a data-URL prefix and whitespace from FileReader output
  const imageBase64 = (body.imageBase64 ?? "").replace(/^data:[^,]*,/, "").replace(/\s+/g, "");
  if (text && imageBase64) {
    return NextResponse.json(
      { ok: false, error: "send text OR imageBase64, not both" },
      { status: 400 }
    );
  }
  if (typeof body.imageBase64 === "string" && !imageBase64) {
    return NextResponse.json(
      { ok: false, error: "image is empty — the file read produced no bytes" },
      { status: 400 }
    );
  }
  // extract-only: no new file, just re-run extraction over the inbox — the
  // drop zone saves a batch with extract:false and then triggers ONE pass
  // here, so a failed last file can never silently skip extraction
  if (!text && !imageBase64) {
    if (body.extract) {
      return NextResponse.json({
        ok: true,
        extraction: runExtraction(),
        hasKey: Boolean(process.env.ANTHROPIC_API_KEY),
      });
    }
    return NextResponse.json(
      { ok: false, error: "text is required (max 4000 chars)" },
      { status: 400 }
    );
  }

  let filename: string;
  let payload: string | Buffer;
  if (imageBase64) {
    // length check BEFORE decoding: base64 is 4 chars per 3 bytes
    if (imageBase64.length > Math.ceil(MAX_IMAGE_BYTES / 3) * 4) {
      return NextResponse.json(
        { ok: false, error: "image exceeds the 5 MB cap (extraction would skip it anyway)" },
        { status: 413 }
      );
    }
    if (!/^[A-Za-z0-9+/]+={0,2}$/.test(imageBase64)) {
      return NextResponse.json(
        { ok: false, error: "imageBase64 is not valid base64" },
        { status: 400 }
      );
    }
    const buf = Buffer.from(imageBase64, "base64");
    if (buf.length === 0 || buf.length > MAX_IMAGE_BYTES) {
      return NextResponse.json(
        { ok: false, error: "image is empty or exceeds the 5 MB cap" },
        { status: 413 }
      );
    }
    const ext = sniffedExt(buf);
    if (!ext) {
      return NextResponse.json(
        { ok: false, error: "not a recognized image — png, jpg, webp or gif only" },
        { status: 400 }
      );
    }
    filename = body.filename?.trim() || `ui_image_${Date.now()}${ext}`;
    if (!isSafeInboxName(filename) || filename.endsWith(".txt")) {
      return NextResponse.json(
        { ok: false, error: "filename must be a plain image name (.png/.jpg/.jpeg/.webp/.gif)" },
        { status: 400 }
      );
    }
    if (canonicalExt(filename) !== ext) {
      return NextResponse.json(
        {
          ok: false,
          error: `the bytes are ${ext.slice(1)} but the name says ${canonicalExt(filename).slice(1) || "nothing"} — the extension must match the actual content (the engine picks the vision media type from it)`,
        },
        { status: 400 }
      );
    }
    payload = buf;
  } else {
    if (!text || text.length > 4000) {
      return NextResponse.json(
        { ok: false, error: "text is required (max 4000 chars)" },
        { status: 400 }
      );
    }
    filename = body.filename?.trim() || `ui_note_${Date.now()}.txt`;
    if (!isSafeInboxName(filename) || !filename.endsWith(".txt")) {
      return NextResponse.json(
        { ok: false, error: "filename must be a plain name ending in .txt" },
        { status: 400 }
      );
    }
    payload = text + "\n";
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
  if (typeof payload === "string") fs.writeFileSync(full, payload, "utf-8");
  else fs.writeFileSync(full, payload);
  const extraction = body.extract ? runExtraction() : { ran: false };
  return NextResponse.json({
    ok: true,
    filename,
    kind: imageBase64 ? "image" : "text",
    hasKey: Boolean(process.env.ANTHROPIC_API_KEY),
    extraction,
  });
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
