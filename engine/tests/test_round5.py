"""Round-5 hardening regressions (adversarial review of the UI write
surface): rejections are keyed by CONTENT not filename, and the offline
rules parser reads the single-variant uplift shape the planner emits."""
import pytest

from planz import db as planz_db
from planz import llm, signals


@pytest.fixture(autouse=True)
def force_rules_backend(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


MSG = "Expect a 25% uplift for Variant V3 in Geo G2 during 2024W05-2024W06."


def test_single_variant_uplift_parses_offline():
    """The what-if template the conversational planner generates must extract
    under the offline rules backend, not only under Claude."""
    events, backend = llm.extract(MSG)
    assert backend == "rules-v1"
    assert len(events) == 1
    e = events[0]
    assert e["event_type"] == "demand_shock"
    assert e["params"]["variant"] == "Variant V3"
    assert e["params"]["geo"] == "Geo G2"
    assert e["params"]["multiplier"] == pytest.approx(1.25)
    assert e["params"]["n_weeks"] == 2


def test_rejection_is_content_keyed_not_filename_keyed(tmp_path):
    """A rejected event must stay rejected even if identical content is
    re-added under a DIFFERENT filename (the round-5 hole)."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "note_a.txt").write_text(MSG, encoding="utf-8")
    db_path = tmp_path / "signals.db"

    signals.extract_inbox(db_path, inbox_dir=inbox)
    assert signals.reject_pending(db_path) == 1        # human rejects it

    # same content, new filename — must NOT reappear as pending
    (inbox / "note_b.txt").write_text(MSG, encoding="utf-8")
    signals.extract_inbox(db_path, inbox_dir=inbox)

    conn = planz_db.connect(db_path)
    try:
        pending = conn.execute("SELECT COUNT(*) FROM signals WHERE"
                               " status = 'pending'").fetchone()[0]
        rejected = conn.execute("SELECT COUNT(*) FROM signals WHERE"
                                " status = 'rejected'").fetchone()[0]
        assert pending == 0                            # not resurrected
        assert rejected == 1
    finally:
        conn.close()
    # and it cannot be approved into existence
    assert signals.approve(db_path) == 0


def test_distinct_content_still_extracts_after_a_rejection(tmp_path):
    """The content filter must be surgical: a DIFFERENT event still lands."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.txt").write_text(MSG, encoding="utf-8")
    db_path = tmp_path / "signals.db"
    signals.extract_inbox(db_path, inbox_dir=inbox)
    signals.reject_pending(db_path)

    (inbox / "b.txt").write_text(
        "Expect a 15% uplift for Variant V1 in Geo G2 during 2024W05-2024W06.",
        encoding="utf-8")
    signals.extract_inbox(db_path, inbox_dir=inbox)
    conn = planz_db.connect(db_path)
    try:
        pending = conn.execute("SELECT COUNT(*) FROM signals WHERE"
                               " status = 'pending'").fetchone()[0]
        assert pending == 1                            # the new one survives
    finally:
        conn.close()
