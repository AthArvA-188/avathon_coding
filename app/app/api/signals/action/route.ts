import { NextRequest, NextResponse } from "next/server";
import { crossOriginBlock, writeDb } from "@/lib/mutate";

// The human gate, over HTTP: approve or reject ONE pending signal by row
// id — byte-for-byte the same UPDATE the CLI runs (--approve-signal <id> /
// signals.approve_one, reject_pending). Targeted-only on purpose: there is
// no batch endpoint, so an image event is approved exactly the way the
// round-4 design requires — one row at a time, after the human compares
// the stored transcription with the image. Approving here does NOT
// re-plan; that stays with the verifier-gated CLI (--agents).

export async function POST(req: NextRequest) {
  const blocked = crossOriginBlock(req);
  if (blocked) return NextResponse.json({ ok: false, error: blocked }, { status: 403 });
  let body: { action?: string; id?: number };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "invalid JSON" }, { status: 400 });
  }
  const { action, id } = body;
  if ((action !== "approve" && action !== "reject") || !Number.isInteger(id)) {
    return NextResponse.json(
      { ok: false, error: "expected {action: 'approve'|'reject', id: integer}" },
      { status: 400 }
    );
  }
  const status = action === "approve" ? "approved" : "rejected";
  const info = writeDb()
    .prepare("UPDATE signals SET status = ? WHERE id = ? AND status = 'pending'")
    .run(status, id);
  return NextResponse.json({
    ok: true,
    changed: info.changes,
    note:
      info.changes === 0
        ? "no pending row with that id — decisions are never overwritten"
        : action === "approve"
          ? "approved — it applies on the next verifier-gated re-plan: python engine/run_pipeline.py --agents"
          : "rejected — permanent: rejections survive re-extraction (content-hash keyed)",
  });
}
