// The ONLY write surface in the app, and it touches exactly two things:
// the `signals` table (approve/reject — the same UPDATEs the CLI human
// gate runs) and the signals inbox directory (create/delete message
// files). Plan tables (mps, shipments, inventory, forecast) are
// solver-owned and stay read-only: re-planning happens through
// `python engine/run_pipeline.py --agents`, never through HTTP.
import Database from "better-sqlite3";
import fs from "fs";
import path from "path";

const ROOT = path.join(process.cwd(), "..");
export const ENGINE_DIR = path.join(ROOT, "engine");
export const INBOX_DIR = path.join(ENGINE_DIR, "signals_inbox");
const DB_FILE = process.env.PLANZ_DB ?? path.join(ROOT, "planz.db");

let wdb: Database.Database | null = null;
export function writeDb(): Database.Database {
  if (!wdb) wdb = new Database(DB_FILE, { fileMustExist: true });
  return wdb;
}

// plain basename, no separators or dots-runs: rules out path traversal
export const SAFE_NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,60}\.(txt|png|jpe?g|webp|gif)$/i;

// Windows reserved device names (with or without extension) resolve to a
// device, not a file — CON.txt, NUL.png, LPT1.txt etc. Reject them.
const RESERVED = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)/i;

export function isSafeInboxName(name: string): boolean {
  return (
    SAFE_NAME.test(name) &&
    !name.includes("..") &&
    !RESERVED.test(name) &&
    !/[. ]$/.test(name) && // Windows strips trailing dot/space -> aliasing
    path.basename(name) === name
  );
}

// CSRF defense for a no-auth localhost tool: a page the user merely visits
// must not be able to actuate the human gate. Cross-site fetches can't set
// Sec-Fetch-Site to same-origin, and a genuine same-origin JSON request
// always carries application/json. Reject anything that fails both.
// Returns an error string, or null if the request is allowed.
export function crossOriginBlock(req: Request): string | null {
  const site = req.headers.get("sec-fetch-site");
  if (site && site !== "same-origin" && site !== "none") {
    return "cross-site request refused (this endpoint is same-origin only)";
  }
  const ct = req.headers.get("content-type") ?? "";
  if (!ct.toLowerCase().includes("application/json")) {
    // a cross-site 'simple request' can't send application/json without a
    // preflight it can't satisfy — so requiring it closes the gap for
    // browsers that don't send Sec-Fetch-Site
    return "content-type must be application/json";
  }
  return null;
}

// files named in labels.json are the eval harness's ground truth — the
// pipeline scores the extractor against them, so the UI must not delete
// or overwrite them
export function labeledFixtures(): Set<string> {
  try {
    return new Set(
      Object.keys(
        JSON.parse(
          fs.readFileSync(path.join(INBOX_DIR, "labels.json"), "utf-8")
        )
      )
    );
  } catch {
    return new Set();
  }
}
