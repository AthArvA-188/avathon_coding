"""LLM-augmented signals tests: the eval harness IS the test — the offline
backend must extract every labeled fixture event exactly, with provenance,
and events must compile into the solver hooks correctly."""
import json

import pytest

from planz import db as planz_db
from planz import llm, signals


@pytest.fixture(autouse=True)
def force_rules_backend(monkeypatch):
    # tests must be deterministic even on machines with an API key
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_eval_harness_perfect_on_fixtures():
    ev = signals.evaluate()
    assert ev["backend"] == "rules-v1"
    assert ev["precision"] == 1.0
    assert ev["recall"] == 1.0
    assert ev["per_file"]["analyst_note.txt"]["extracted"] == 0   # noise


def test_extraction_provenance_and_gate(tmp_path):
    db_path = tmp_path / "signals.db"
    found = signals.extract_inbox(db_path)
    assert len(found) == 7

    conn = planz_db.connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM signals").fetchall()
        assert len(rows) == 7
        for r in rows:
            assert r["status"] == "pending"          # nothing auto-applies
            assert r["backend"] == "rules-v1"
            assert r["prompt_version"] == llm.PROMPT_VERSION
            assert len(r["evidence"]) > 20           # quoted span present
            assert r["source"].endswith(".txt")
            json.loads(r["params_json"])             # valid payload
        cap_evidence = conn.execute(
            "SELECT evidence FROM signals WHERE event_type = 'supply_cap'"
            ).fetchone()["evidence"]
        assert "4,500 units per week" in cap_evidence
    finally:
        conn.close()

    assert signals.approve(db_path) == 7
    conn = planz_db.connect(db_path)
    try:
        approved = signals.load_approved(conn)
        assert len(approved) == 7
    finally:
        conn.close()


def test_compile_events_to_solver_hooks(tmp_path):
    db_path = tmp_path / "signals.db"
    signals.extract_inbox(db_path)
    signals.approve(db_path)
    conn = planz_db.connect(db_path)
    try:
        constraints = signals.compile_events(signals.load_approved(conn))
    finally:
        conn.close()

    caps = constraints["extra_prod_caps"]
    assert len(caps) == 1
    variants, weeks, cap = caps[0]
    assert set(variants) == {"Variant V2", "Variant V4"}
    assert list(weeks) == list(range(0, 6))
    assert cap == 4500.0

    blocks = constraints["mode_blocks"]
    assert blocks == [("Geo G1", "Fast Boat Ocean", range(4, 8))]

    mults = constraints["demand_mults"]
    assert len(mults) == 5
    v3 = [m for m in mults if m[0] == "Variant V3" and m[3] == 2.0]
    assert len(v3) == 1 and v3[0][1] == "Geo G1" and list(v3[0][2]) == list(range(0, 13))


def test_low_confidence_stays_pending(tmp_path, monkeypatch):
    db_path = tmp_path / "signals.db"
    monkeypatch.setattr(
        llm, "extract",
        lambda text: ([{"event_type": "supply_cap",
                        "params": {"variants": ["Variant V1"],
                                   "start_offset": 0, "n_weeks": 1,
                                   "weekly_cap": 1.0},
                        "evidence": "maybe? low confidence extraction here",
                        "confidence": 0.3}], "stub"))
    signals.extract_inbox(db_path)
    assert signals.approve(db_path, min_confidence=0.8) == 0
    conn = planz_db.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM signals WHERE"
                            " status = 'pending'").fetchone()[0] > 0
    finally:
        conn.close()


def test_fabricated_evidence_cannot_auto_approve(tmp_path, monkeypatch):
    # a quote that is NOT verbatim in the source is zero-confidence forever
    monkeypatch.setattr(
        llm, "extract",
        lambda text: ([{"event_type": "demand_shock",
                        "params": {"variant": "Variant V1", "geo": "Geo G1",
                                   "start_offset": 0, "n_weeks": 4,
                                   "multiplier": 3.0},
                        "evidence": "Management approved tripling output",
                        "confidence": 1.0}], "stub"))
    db_path = tmp_path / "signals.db"
    signals.extract_inbox(db_path)
    assert signals.approve(db_path) == 0
    conn = planz_db.connect(db_path)
    try:
        row = conn.execute("SELECT confidence, status FROM signals").fetchone()
        assert row["confidence"] == 0.0 and row["status"] == "pending"
    finally:
        conn.close()


def test_sanitizer_drops_out_of_bounds_and_unknown_events():
    valid, dropped = llm.sanitize([
        {"event_type": "demand_shock",                  # negative offset
         "params": {"variant": "Variant V1", "geo": "Geo G1",
                    "start_offset": -17, "n_weeks": 8, "multiplier": 1.2},
         "evidence": "x", "confidence": 1.0},
        {"event_type": "demand_shock",                  # beyond horizon
         "params": {"variant": "Variant V1", "geo": "Geo G1",
                    "start_offset": 40, "n_weeks": 40, "multiplier": 1.2},
         "evidence": "x", "confidence": 1.0},
        {"event_type": "demand_shock",                  # injection-scale mult
         "params": {"variant": "Variant V1", "geo": "Geo G1",
                    "start_offset": 0, "n_weeks": 52, "multiplier": 0.05},
         "evidence": "x", "confidence": 1.0},
        {"event_type": "demand_shock",                  # capped variant
         "params": {"variant": "Variant V10", "geo": "Geo G1",
                    "start_offset": 0, "n_weeks": 4, "multiplier": 1.5},
         "evidence": "x", "confidence": 1.0},
        {"event_type": "explode_database",              # unknown type
         "params": {"start_offset": 0, "n_weeks": 1},
         "evidence": "x", "confidence": 1.0},
        {"event_type": "supply_cap",                    # the one good event
         "params": {"variants": ["Variant V2"], "start_offset": 0,
                    "n_weeks": 6, "weekly_cap": 4500.0},
         "evidence": "x", "confidence": 1.0},
        {"event_type": "supply_cap",                    # exact duplicate
         "params": {"variants": ["Variant V2"], "start_offset": 0,
                    "n_weeks": 6, "weekly_cap": 4500.0},
         "evidence": "x", "confidence": 1.0},
    ])
    assert len(valid) == 1 and valid[0]["event_type"] == "supply_cap"
    assert dropped == 6


def test_rejection_survives_reextraction(tmp_path):
    db_path = tmp_path / "signals.db"
    signals.extract_inbox(db_path)
    assert signals.reject_pending(db_path) == 7
    signals.extract_inbox(db_path)                      # re-scan the inbox
    conn = planz_db.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM signals WHERE"
                            " status = 'rejected'").fetchone()[0] == 7
        assert conn.execute("SELECT COUNT(*) FROM signals WHERE"
                            " status = 'pending'").fetchone()[0] == 0
    finally:
        conn.close()
    assert signals.approve(db_path) == 0                # stays rejected
