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
  (as multisets — duplicated extractions count as errors);
- images (docs D30) ride the same rails with one honest difference: the
  evidence-vs-transcription check is self-referential (the model authors
  both sides), so vision confidence is capped below the batch-approve floor
  and image events require targeted per-row human approval (approve_one),
  with the transcription + image content hash persisted for that comparison;
  offline (or on API error / oversize file) images are skipped — never
  guessed at, and never pruned as if they'd stopped extracting.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import db, llm

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INBOX = ROOT / "engine" / "signals_inbox"


def _hash(source: str, event_type: str, params: dict, extra: str = "") -> str:
    # `extra` carries the image sha256 for vision rows: if the picture's
    # bytes change under the same filename, the event re-keys instead of
    # silently keeping a stale transcription. Text rows omit it, keeping
    # their hashes stable across upgrades.
    d: dict = {"s": source, "t": event_type, "p": params}
    if extra:
        d["x"] = extra
    return hashlib.sha256(json.dumps(
        d, sort_keys=True).encode()).hexdigest()[:24]


def extract_inbox(db_path, inbox_dir=None,
                  skipped_out: list | None = None) -> list[dict]:
    """Extract events from every .txt AND image file in the inbox and persist
    as 'pending'. Rows are keyed by content hash: existing approved/rejected
    rows are left untouched; pending rows that no longer extract are pruned —
    but a file that was SKIPPED (no vision backend, API error, oversize
    image) is exempt from pruning: "not attempted" is not "no longer
    extracts", so an offline re-run can never delete image events that are
    waiting on a human (adversarial review round 4).

    Images (docs D30) go through the vision backend; the evidence-substring
    rule is enforced against the model's own transcription (which is
    persisted, with the image's sha256, so the human gate can compare it
    with the image). Because that check is self-referential — the model
    authors both sides — vision confidence is capped at
    llm.VISION_CONF_CEILING, below the batch-approve floor: image events
    are only approvable one-by-one via approve_one() / --approve-signal.
    Without an API key, image files are skipped — never guessed at.
    Pass `skipped_out` (a list) to receive (filename, reason) pairs."""
    inbox = Path(inbox_dir or DEFAULT_INBOX)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    found: list[dict] = []
    skipped: list[tuple[str, str]] = []
    files = sorted(p for p in inbox.iterdir() if p.is_file() and
                   (p.suffix.lower() == ".txt" or
                    p.suffix.lower() in llm.IMAGE_MEDIA))
    for f in files:
        is_image = f.suffix.lower() in llm.IMAGE_MEDIA
        if not is_image:
            text = f.read_text(encoding="utf-8")
            events, backend = llm.extract(text)
            haystack, transcription, sha = text, "", ""
            prompt_version = llm.PROMPT_VERSION
        else:
            if f.stat().st_size > llm.MAX_IMAGE_BYTES:
                skipped.append((f.name, "image-too-large"))
                continue
            data = f.read_bytes()
            events, backend, transcription = llm.extract_image(
                data, llm.IMAGE_MEDIA[f.suffix.lower()])
            if backend.startswith("none("):
                # not attempted (no key / API error) — leave any existing
                # pending rows for this file alone
                skipped.append((f.name, backend))
                continue
            haystack, sha = transcription, hashlib.sha256(data).hexdigest()
            prompt_version = llm.VISION_PROMPT_VERSION
        flat = haystack.replace("\n", " ")
        for e in events:
            # provenance must be real: a quote that is not verbatim in the
            # source (text) or the transcription (image) cannot carry
            # auto-approvable confidence
            if e["evidence"] and (e["evidence"] in haystack
                                  or e["evidence"] in flat):
                conf = e["confidence"]
            else:
                conf = 0.0
            if is_image:
                conf = min(conf, llm.VISION_CONF_CEILING)
            found.append({**e, "confidence": conf, "source": f.name,
                          "backend": backend,
                          "prompt_version": prompt_version,
                          "transcription": transcription,
                          "source_sha256": sha,
                          "hash": _hash(f.name, e["event_type"], e["params"],
                                        extra=sha)})
    if skipped_out is not None:
        skipped_out.extend(skipped)

    conn = db.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            db.init_signals_schema(conn)
            hashes = [e["hash"] for e in found]
            skipped_names = [name for name, _ in skipped]
            ph = ",".join("?" for _ in hashes) or "''"
            sk = ",".join("?" for _ in skipped_names) or "''"
            conn.execute(f"DELETE FROM signals WHERE status = 'pending'"
                         f" AND content_hash NOT IN ({ph})"
                         f" AND source NOT IN ({sk})",
                         hashes + skipped_names)
            conn.executemany(
                "INSERT INTO signals (source, event_type, params_json,"
                " evidence, backend, prompt_version, confidence, status,"
                " created_at, content_hash, transcription, source_sha256)"
                " VALUES (?,?,?,?,?,?,?,'pending',?,?,?,?)"
                " ON CONFLICT (content_hash) DO NOTHING",
                [(e["source"], e["event_type"], json.dumps(e["params"]),
                  e["evidence"], e["backend"], e["prompt_version"],
                  e["confidence"], now, e["hash"], e["transcription"],
                  e["source_sha256"]) for e in found])
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


def approve_one(db_path, signal_id: int) -> int:
    """Targeted human approval by row id — the only way an image event can
    be approved (its confidence is capped below the batch floor because the
    evidence check is self-referential for images): the human compares the
    stored transcription with the image, then names the row."""
    conn = db.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute(
                "UPDATE signals SET status = 'approved'"
                " WHERE id = ? AND status = 'pending'", (signal_id,))
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
    skipped: list[str] = []
    backend = None
    for fname, expected in labels.items():
        suffix = Path(fname).suffix.lower()
        if suffix in llm.IMAGE_MEDIA:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                # vision has no offline stand-in: skip honestly rather than
                # score a backend that never ran
                skipped.append(fname)
                continue
            got, vb, _ = llm.extract_image(
                (inbox / fname).read_bytes(), llm.IMAGE_MEDIA[suffix])
            if vb.startswith("none("):
                # API error: the backend never ran — that is a skip, not a
                # recall failure (adversarial review round 4)
                skipped.append(fname)
                continue
            backend = vb
        else:
            got, backend = llm.extract(
                (inbox / fname).read_text(encoding="utf-8"))
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
            "recall": recall, "per_file": per_file, "skipped": skipped}
