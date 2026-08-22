"""LLM-augmented signals (docs D27): inbox -> typed events -> solver inputs.

Auditability is the design center:
- every extracted event stores its source file, the quoted evidence span
  (verified verbatim against the source — a fabricated quote zeroes the
  confidence so it can never auto-approve), the backend that actually
  produced it, the prompt version, and a confidence;
- events are keyed by content hash: re-extraction NEVER disturbs a human's
  approved/rejected decisions — only unclaimed pending rows are refreshed;
- nothing touches a plan until its status is 'approved', and approval is an
  explicit act (signals.approve / --approve-signals), never a side effect;
- an eval harness scores any backend against labeled fixture messages
  (as multisets — duplicated extractions count as errors).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import db, llm

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INBOX = ROOT / "engine" / "signals_inbox"


def _hash(source: str, event_type: str, params: dict) -> str:
    return hashlib.sha256(json.dumps(
        {"s": source, "t": event_type, "p": params},
        sort_keys=True).encode()).hexdigest()[:24]


def extract_inbox(db_path, inbox_dir=None) -> list[dict]:
    """Extract events from every .txt in the inbox and persist as 'pending'.
    Rows are keyed by content hash: existing approved/rejected rows are left
    untouched; pending rows that no longer extract are pruned."""
    inbox = Path(inbox_dir or DEFAULT_INBOX)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    found: list[dict] = []
    for f in sorted(inbox.glob("*.txt")):
        text = f.read_text(encoding="utf-8")
        events, backend = llm.extract(text)
        flat = text.replace("\n", " ")
        for e in events:
            # provenance must be real: a quote that is not verbatim in the
            # source cannot carry auto-approvable confidence
            if e["evidence"] and (e["evidence"] in text
                                  or e["evidence"] in flat):
                conf = e["confidence"]
            else:
                conf = 0.0
            found.append({**e, "confidence": conf, "source": f.name,
                          "backend": backend,
                          "hash": _hash(f.name, e["event_type"], e["params"])})

    conn = db.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            db.init_signals_schema(conn)
            hashes = [e["hash"] for e in found]
            ph = ",".join("?" for _ in hashes) or "''"
            conn.execute(f"DELETE FROM signals WHERE status = 'pending'"
                         f" AND content_hash NOT IN ({ph})", hashes)
            conn.executemany(
                "INSERT INTO signals (source, event_type, params_json,"
                " evidence, backend, prompt_version, confidence, status,"
                " created_at, content_hash) VALUES (?,?,?,?,?,?,?,'pending',?,?)"
                " ON CONFLICT (content_hash) DO NOTHING",
                [(e["source"], e["event_type"], json.dumps(e["params"]),
                  e["evidence"], e["backend"], llm.PROMPT_VERSION,
                  e["confidence"], now, e["hash"]) for e in found])
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return found


def approve(db_path, min_confidence: float = 0.8) -> int:
    """The human gate. Explicit call required; events below the confidence
    floor stay pending for manual review."""
    conn = db.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute(
                "UPDATE signals SET status = 'approved'"
                " WHERE status = 'pending' AND confidence >= ?",
                (min_confidence,))
            conn.execute("COMMIT")
            return cur.rowcount
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def reject_pending(db_path) -> int:
    """Human override: mark every pending event rejected. Rejected rows are
    keyed by content hash and survive re-extraction — a rejected event can
    never be silently re-approved."""
    conn = db.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute("UPDATE signals SET status = 'rejected'"
                               " WHERE status = 'pending'")
            conn.execute("COMMIT")
            return cur.rowcount
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def load_approved(conn: sqlite3.Connection) -> list[dict]:
    return [{"event_type": r["event_type"],
             "params": json.loads(r["params_json"]),
             "source": r["source"]}
            for r in conn.execute(
                "SELECT * FROM signals WHERE status = 'approved'")]


def pending_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM signals WHERE"
                        " status = 'pending'").fetchone()[0]


def compile_events(events: list[dict]) -> dict:
    """Approved events -> the solver hooks (mps/heuristic understand these).
    Windows are defensively clamped to the horizon even though sanitize()
    already bounds them."""
    caps, mults, blocks = [], [], []
    for e in events:
        p = e["params"]
        start = max(0, int(p["start_offset"]))
        end = min(llm.H, start + int(p["n_weeks"]))
        weeks = range(start, end)
        if not len(weeks):
            continue
        if e["event_type"] == "supply_cap":
            caps.append((tuple(p["variants"]), weeks, float(p["weekly_cap"])))
        elif e["event_type"] == "demand_shock":
            mults.append((p["variant"], p.get("geo"), weeks,
                          float(p["multiplier"])))
        elif e["event_type"] == "freight_disruption":
            blocks.append((p["geo"], p["mode"], weeks))
    return {"extra_prod_caps": caps, "demand_mults": mults,
            "mode_blocks": blocks}


def evaluate(inbox_dir=None) -> dict:
    """Score the active backend against the labeled fixtures. Events are
    compared as MULTISETS (type + full params): duplicates count as false
    positives, and an event is correct only on an exact match."""
    inbox = Path(inbox_dir or DEFAULT_INBOX)
    labels = json.loads((inbox / "labels.json").read_text(encoding="utf-8"))
    tp = fp = fn = 0
    per_file = {}
    backend = None
    for fname, expected in labels.items():
        got, backend = llm.extract((inbox / fname).read_text(encoding="utf-8"))
        want = sorted(json.dumps({"t": e["event_type"], "p": e["params"]},
                                 sort_keys=True) for e in expected)
        have = sorted(json.dumps({"t": e["event_type"], "p": e["params"]},
                                 sort_keys=True) for e in got)
        matched = 0
        rest = list(want)
        for h in have:
            if h in rest:
                rest.remove(h)
                matched += 1
        tp += matched
        fp += len(have) - matched
        fn += len(want) - matched
        per_file[fname] = {"expected": len(want), "extracted": len(have),
                           "matched": matched}
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {"backend": backend or llm.backend_name(), "precision": precision,
            "recall": recall, "per_file": per_file}
