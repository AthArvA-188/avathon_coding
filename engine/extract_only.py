"""Inbox extraction only — the thin entry point the UI's "Save & extract"
button spawns (docs D31). Runs signals.extract_inbox (same gate semantics
as `run_pipeline.py --signals`) but skips the eval pass, so a single new
message doesn't trigger a full labeled-fixture scoring run. Prints a
one-line JSON summary for the caller."""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from planz import signals  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _pending(db: str) -> int:
    try:
        c = sqlite3.connect(db)
        try:
            return c.execute("SELECT COUNT(*) FROM signals"
                             " WHERE status = 'pending'").fetchone()[0]
        finally:
            c.close()
    except sqlite3.OperationalError:
        return 0   # signals table not created yet


def main() -> None:
    db = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "planz.db")
    # count genuinely-new pending rows, not the whole re-extracted inbox:
    # extract_inbox re-reads every file and returns all extracted events,
    # but already-approved/duplicate rows are deduped away on insert
    # (round-5 fix: the old summary counted those and over-reported)
    before = _pending(db)
    skipped: list = []
    signals.extract_inbox(db, skipped_out=skipped)
    after = _pending(db)
    print(json.dumps({
        "new_pending": max(0, after - before),
        "pending_total": after,
        "skipped": [{"file": n, "reason": r} for n, r in skipped],
    }))


if __name__ == "__main__":
    main()
