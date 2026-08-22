"""Image-based signal pipeline tests (docs D30). The vision backend is
stubbed — no network — so what's under test is the trust boundary: the
same sanitize() gate, the evidence-vs-transcription rule, offline skipping,
provenance columns, and the schema migration."""
import hashlib
import json
import sqlite3

import pytest

from planz import db as planz_db
from planz import llm, signals


@pytest.fixture(autouse=True)
def no_real_key(monkeypatch):
    # deterministic by default; individual tests set a dummy key when they
    # stub the network layer
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


GOOD_EVENT = {"event_type": "freight_disruption",
              "params": {"geo": "Geo G4", "mode": "Air",
                         "start_offset": 8, "n_weeks": 2},
              "evidence": "Air service to Geo G4 will be suspended.",
              "confidence": 0.9}
TRANSCRIPTION = ("CARRIER SERVICE ALERT\n"
                 "Air service to Geo G4 will be suspended.")


def _image_inbox(tmp_path, name="notice.png", data=b"\x89PNG fake bytes"):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / name).write_bytes(data)
    return inbox, data


def test_images_skipped_without_key(tmp_path):
    """No key -> no vision backend -> the file is skipped, never guessed at,
    and the batch never crashes."""
    events, backend, transcription = llm.extract_image(b"junk", "image/png")
    assert events == [] and backend == "none(vision-unavailable)"
    assert transcription == ""

    inbox, _ = _image_inbox(tmp_path)
    db_path = tmp_path / "signals.db"
    found = signals.extract_inbox(db_path, inbox_dir=inbox)
    assert found == []


def test_vision_rows_persist_full_provenance(tmp_path, monkeypatch):
    """A vision event lands with the vision prompt version, the model's
    transcription, and the image's content hash — the audit trail a human
    needs to check the read against the picture."""
    inbox, data = _image_inbox(tmp_path)
    monkeypatch.setattr(llm, "extract_image", lambda d, m, drop_reasons=None: (
        [dict(GOOD_EVENT)], "claude:claude-sonnet-5+vision", TRANSCRIPTION))
    db_path = tmp_path / "signals.db"
    found = signals.extract_inbox(db_path, inbox_dir=inbox)
    assert len(found) == 1

    conn = planz_db.connect(db_path)
    try:
        r = conn.execute("SELECT * FROM signals").fetchone()
        assert r["source"] == "notice.png"
        assert r["backend"] == "claude:claude-sonnet-5+vision"
        assert r["prompt_version"] == llm.VISION_PROMPT_VERSION
        assert r["transcription"] == TRANSCRIPTION
        assert r["source_sha256"] == hashlib.sha256(data).hexdigest()
        # the self-referential evidence check can't prove non-fabrication,
        # so vision confidence is capped below the 0.8 batch-approve floor
        assert r["confidence"] == pytest.approx(llm.VISION_CONF_CEILING)
        assert r["status"] == "pending"                # gate still closed
    finally:
        conn.close()


def test_vision_events_never_batch_approve_but_approve_one_works(
        tmp_path, monkeypatch):
    """Round-4 hardening: approve() (the 0.8-floor batch gate) must never
    catch an image event; approve_one(id) — targeted, after the human
    compares transcription vs image — must."""
    inbox, _ = _image_inbox(tmp_path)
    monkeypatch.setattr(llm, "extract_image", lambda d, m, drop_reasons=None: (
        [dict(GOOD_EVENT, confidence=1.0)],
        "claude:claude-sonnet-5+vision", TRANSCRIPTION))
    db_path = tmp_path / "signals.db"
    signals.extract_inbox(db_path, inbox_dir=inbox)

    assert signals.approve(db_path) == 0               # batch gate: excluded
    conn = planz_db.connect(db_path)
    try:
        row_id = conn.execute("SELECT id FROM signals").fetchone()["id"]
    finally:
        conn.close()
    assert signals.approve_one(db_path, row_id) == 1   # targeted: works
    assert signals.approve_one(db_path, row_id) == 0   # idempotent
    conn = planz_db.connect(db_path)
    try:
        assert len(signals.load_approved(conn)) == 1
    finally:
        conn.close()


def test_offline_rerun_never_prunes_pending_image_rows(tmp_path, monkeypatch):
    """Round-4 fix for a real data-loss hole: a pending image event created
    online must SURVIVE a later offline (or API-error) re-extraction —
    'not attempted' is not 'no longer extracts'."""
    inbox, _ = _image_inbox(tmp_path)
    db_path = tmp_path / "signals.db"
    monkeypatch.setattr(llm, "extract_image", lambda d, m, drop_reasons=None: (
        [dict(GOOD_EVENT)], "claude:claude-sonnet-5+vision", TRANSCRIPTION))
    signals.extract_inbox(db_path, inbox_dir=inbox)     # "online" run

    monkeypatch.undo()                                  # real extract_image
    # make "offline" true even on a machine whose shell has a real key
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    skipped: list = []                                  # no key -> skipped
    found = signals.extract_inbox(db_path, inbox_dir=inbox,
                                  skipped_out=skipped)
    assert found == []
    assert skipped == [("notice.png", "none(vision-unavailable)")]
    conn = planz_db.connect(db_path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM signals WHERE"
                         " status = 'pending'").fetchone()[0]
        assert n == 1                                   # still awaiting human
    finally:
        conn.close()


def test_changed_image_bytes_rekey_the_event(tmp_path, monkeypatch):
    """The image's sha256 is part of the content hash: replacing the picture
    under the same filename refreshes the pending row (new transcription,
    new hash) instead of silently keeping stale provenance."""
    inbox, _ = _image_inbox(tmp_path, data=b"image v1")
    db_path = tmp_path / "signals.db"
    monkeypatch.setattr(llm, "extract_image", lambda d, m, drop_reasons=None: (
        [dict(GOOD_EVENT)], "claude:claude-sonnet-5+vision",
        TRANSCRIPTION + f"\n[bytes:{d!r}]"))
    signals.extract_inbox(db_path, inbox_dir=inbox)

    (inbox / "notice.png").write_bytes(b"image v2 - different bytes")
    signals.extract_inbox(db_path, inbox_dir=inbox)
    conn = planz_db.connect(db_path)
    try:
        rows = conn.execute("SELECT source_sha256 FROM signals").fetchall()
        assert len(rows) == 1                           # re-keyed, not duped
        assert rows[0]["source_sha256"] == hashlib.sha256(
            b"image v2 - different bytes").hexdigest()
    finally:
        conn.close()


def test_oversize_image_skipped_never_read(tmp_path, monkeypatch):
    """Files over MAX_IMAGE_BYTES are skipped before any read or API call —
    no memory blowup, no vision spend, and existing pending rows survive."""
    inbox, _ = _image_inbox(tmp_path,
                            data=b"\0" * (llm.MAX_IMAGE_BYTES + 1))

    def explode(d, m):
        raise AssertionError("oversize image must not reach the backend")

    monkeypatch.setattr(llm, "extract_image", explode)
    db_path = tmp_path / "signals.db"
    skipped: list = []
    found = signals.extract_inbox(db_path, inbox_dir=inbox,
                                  skipped_out=skipped)
    assert found == []
    assert skipped == [("notice.png", "image-too-large")]


def test_empty_evidence_zeroes_confidence(tmp_path, monkeypatch):
    """An image event with no evidence quote at all must not keep its
    confidence — same rule as a fabricated quote."""
    inbox, _ = _image_inbox(tmp_path)
    monkeypatch.setattr(llm, "extract_image", lambda d, m, drop_reasons=None: (
        [dict(GOOD_EVENT, evidence="")],
        "claude:claude-sonnet-5+vision", TRANSCRIPTION))
    db_path = tmp_path / "signals.db"
    signals.extract_inbox(db_path, inbox_dir=inbox)
    conn = planz_db.connect(db_path)
    try:
        assert conn.execute("SELECT confidence FROM signals"
                            ).fetchone()["confidence"] == 0.0
    finally:
        conn.close()


def test_evidence_must_match_transcription(tmp_path, monkeypatch):
    """A quote that is not in the model's own transcription zeroes the
    confidence (a consistency check, honestly weaker than the text path's
    source-verbatim rule — hence the separate confidence ceiling)."""
    inbox, _ = _image_inbox(tmp_path)
    fabricated = dict(GOOD_EVENT, evidence="A sentence the image never had.")
    monkeypatch.setattr(llm, "extract_image", lambda d, m, drop_reasons=None: (
        [fabricated], "claude:claude-sonnet-5+vision", TRANSCRIPTION))
    db_path = tmp_path / "signals.db"
    signals.extract_inbox(db_path, inbox_dir=inbox)

    conn = planz_db.connect(db_path)
    try:
        r = conn.execute("SELECT confidence FROM signals").fetchone()
        assert r["confidence"] == 0.0
    finally:
        conn.close()
    assert signals.approve(db_path) == 0


def test_vision_output_passes_same_sanitize(monkeypatch):
    """extract_image() runs the identical sanitize() boundary: an injected
    out-of-bounds multiplier and an unknown variant are dropped; the valid
    event survives. (The stub replaces only the network call.)"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")
    poisoned = [
        dict(GOOD_EVENT),
        {"event_type": "demand_shock",
         "params": {"variant": "Variant V2", "geo": "Geo G3",
                    "start_offset": 22, "n_weeks": 2, "multiplier": 99.0},
         "evidence": "x", "confidence": 1.0},           # injected multiplier
        {"event_type": "demand_shock",
         "params": {"variant": "Variant V99", "geo": "Geo G3",
                    "start_offset": 22, "n_weeks": 2, "multiplier": 1.3},
         "evidence": "x", "confidence": 1.0},           # unknown entity
    ]
    monkeypatch.setattr(llm, "_extract_claude_image",
                        lambda d, m: (poisoned, TRANSCRIPTION))
    events, backend, transcription = llm.extract_image(b"img", "image/png")
    assert backend == "claude:claude-sonnet-5+vision"
    assert transcription == TRANSCRIPTION
    assert [e["event_type"] for e in events] == ["freight_disruption"]


def test_vision_api_error_never_mislabels(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")

    def boom(d, m):
        raise RuntimeError("api down")

    monkeypatch.setattr(llm, "_extract_claude_image", boom)
    events, backend, transcription = llm.extract_image(b"img", "image/png")
    assert events == [] and backend == "none(vision-error)"


def test_schema_migration_adds_vision_columns(tmp_path):
    """A pre-D30 signals table (content_hash present, no vision columns) is
    migrated additively — existing rows and statuses survive."""
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE signals (
        id INTEGER PRIMARY KEY, source TEXT NOT NULL,
        event_type TEXT NOT NULL, params_json TEXT NOT NULL,
        evidence TEXT NOT NULL, backend TEXT NOT NULL,
        prompt_version TEXT NOT NULL, confidence REAL NOT NULL,
        status TEXT NOT NULL, created_at TEXT NOT NULL,
        content_hash TEXT NOT NULL)""")
    conn.execute("INSERT INTO signals VALUES (1,'a.txt','supply_cap','{}',"
                 "'e','rules-v1','v3',1.0,'approved','2026-01-01','h1')")
    conn.commit()

    planz_db.init_signals_schema(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(signals)")}
    assert {"transcription", "source_sha256"} <= cols
    r = conn.execute("SELECT status, transcription, source_sha256"
                     " FROM signals").fetchone()
    assert r == ("approved", "", "")
    conn.close()


def _eval_inbox(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "note.txt").write_text("nothing actionable here",
                                    encoding="utf-8")
    (inbox / "notice.png").write_bytes(b"\x89PNG fake")
    (inbox / "labels.json").write_text(json.dumps({
        "note.txt": [],
        "notice.png": [{"event_type": "freight_disruption",
                        "params": {"geo": "Geo G4", "mode": "Air",
                                   "start_offset": 8, "n_weeks": 2}}],
    }), encoding="utf-8")
    return inbox


def test_evaluate_skips_image_fixtures_offline(tmp_path):
    """Offline, image fixtures are reported as skipped — not silently scored
    as failures against a backend that never ran."""
    ev = signals.evaluate(inbox_dir=_eval_inbox(tmp_path))
    assert ev["skipped"] == ["notice.png"]
    assert "notice.png" not in ev["per_file"]
    assert ev["precision"] == 1.0 and ev["recall"] == 1.0   # text-only score


def test_evaluate_treats_vision_api_error_as_skip(tmp_path, monkeypatch):
    """Round-4 fix: with a key set but the vision call failing, the image
    fixture is a SKIP (the backend never ran), not a recall failure."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-used")

    def boom(*a, **k):
        raise RuntimeError("api down")

    monkeypatch.setattr(llm, "_extract_claude_image", boom)
    monkeypatch.setattr(llm, "_extract_claude", boom)   # text falls back to
    ev = signals.evaluate(inbox_dir=_eval_inbox(tmp_path))  # rules, offline
    assert ev["skipped"] == ["notice.png"]
    assert ev["recall"] == 1.0                          # not a false negative
