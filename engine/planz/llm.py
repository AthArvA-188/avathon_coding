"""Pluggable signal extractor — the LLM slot (docs D27).

`extract(text)` turns one unstructured planner message into zero or more
typed events and reports which backend actually produced them. Two
interchangeable backends:

- **Anthropic Claude**, used automatically when ANTHROPIC_API_KEY is set.
- **rules-v1**, a deterministic pattern parser that stands in the same slot
  so the whole prototype runs offline for reviewers.

Trust boundary: NOTHING a backend emits is taken at face value. Every event
passes `sanitize()` — type enum, required keys, numeric coercion, horizon
bounds, known entities, multiplier limits, per-message dedup — and invalid
events are dropped and counted, never allowed to crash the batch or reach
the database. (An adversarial review demonstrated prompt-injected events
sailing through an earlier version; this boundary is the fix, together with
the evidence-substring check and demand-delta guard in signals.py/agents.py.)

Event schema (params_json):
  supply_cap        {variants: [..], start_offset, n_weeks, weekly_cap}
  demand_shock      {variant, geo, start_offset, n_weeks, multiplier}
  freight_disruption{geo, mode, start_offset, n_weeks}
`start_offset` counts weeks from the horizon start (2023W40 = 0).
"""
from __future__ import annotations

import json
import os
import re

from . import features as ft
from . import params

PROMPT_VERSION = "v2"
H = 52
H_BASE = ft.offset_of(params.HORIZON_START)      # derived, not hardcoded

_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
              "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
              "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
              "fifteen": 15, "twenty": 20, "twenty-six": 26}

CORE_VARIANTS = ["Variant V1", "Variant V2", "Variant V3", "Variant V4"]
ALL_VARIANTS = {f"Variant V{i}" for i in range(1, 13)}
KNOWN_GEOS = {f"Geo G{i}" for i in range(1, 6)}
KNOWN_MODES = {"Air", "Ground", "Fast Boat Ocean", "Standard Ocean"}
MULT_MIN, MULT_MAX = 0.2, 5.0

CLAUDE_PROMPT = f"""You are a demand-planning signal extractor (prompt {PROMPT_VERSION}).
Read the message and emit a JSON array of planning events. Event types and
required params:
- supply_cap: variants (list like ["Variant V2"]), start_offset, n_weeks, weekly_cap
- demand_shock: variant, geo, start_offset, n_weeks, multiplier
- freight_disruption: geo, mode, start_offset, n_weeks
start_offset counts weeks from the planning horizon start, 2023W40 (fiscal
calendar; "next quarter" = 2023Q4 = offsets 0-12; fiscal 2024Q1 starts at
offset 13; week label 2023W44 = offset 4, 2024W02 = offset 14). Retailers
R1-R4 sell in Geo G1. "Core variants" = V1-V4. For each event also return
"evidence" (an exact quote copied verbatim from the message) and
"confidence" (0-1). Return [] if the message contains no actionable planning
event. Flat JSON objects only, no prose, no markdown fences."""


def _n(week_label: str) -> int:
    return ft.offset_of(week_label) - H_BASE


def _word_num(w: str) -> int | None:
    if w.isdigit():
        return int(w)
    return _NUM_WORDS.get(w.lower())


def backend_name() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude:claude-sonnet-5"
    return "rules-v1"


def sanitize(events: list[dict]) -> tuple[list[dict], int]:
    """The trust boundary: keep only well-formed, in-bounds events over known
    entities; drop (and count) everything else. Deduplicates per message."""
    valid, seen, dropped = [], set(), 0
    for e in events:
        try:
            et = e["event_type"]
            p = dict(e["params"])
            start = int(p["start_offset"])
            n = int(p["n_weeks"])
            assert 0 <= start < H and 1 <= n and start + n <= H
            if et == "supply_cap":
                p["variants"] = sorted(set(p["variants"]))
                assert p["variants"] and set(p["variants"]) <= ALL_VARIANTS
                p["weekly_cap"] = float(p["weekly_cap"])
                assert p["weekly_cap"] > 0
            elif et == "demand_shock":
                assert p["variant"] in set(CORE_VARIANTS)   # prototype policy:
                # deal/exclusive volumes are contractual — shocks on them are
                # a human conversation, not an auto-applied multiplier
                assert p.get("geo") in KNOWN_GEOS           # no geo => no event
                p["multiplier"] = float(p["multiplier"])
                assert MULT_MIN <= p["multiplier"] <= MULT_MAX
            elif et == "freight_disruption":
                assert p["geo"] in KNOWN_GEOS and p["mode"] in KNOWN_MODES
            else:
                raise ValueError(et)
            p["start_offset"], p["n_weeks"] = start, n
            key = json.dumps({"t": et, "p": p}, sort_keys=True)
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
            valid.append({"event_type": et, "params": p,
                          "evidence": str(e.get("evidence", ""))[:500],
                          "confidence": max(0.0, min(1.0,
                                            float(e.get("confidence", 0.0))))})
        except Exception:
            dropped += 1
    return valid, dropped


def extract(text: str) -> tuple[list[dict], str]:
    """-> (sanitized events, backend that actually produced them)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            raw = _extract_claude(text)
            events, _ = sanitize(raw)
            return events, backend_name()
        except Exception:
            # fall back, but NEVER mislabel provenance as the LLM's output
            events, _ = sanitize(_extract_rules(text))
            return events, "rules-v1(fallback)"
    events, _ = sanitize(_extract_rules(text))
    return events, "rules-v1"


# ---------------- rules backend ----------------

def _sentence_of(text: str, idx: int) -> str:
    start = max(text.rfind(".", 0, idx), text.rfind("\n\n", 0, idx)) + 1
    end = text.find(".", idx)
    return text[start:end + 1 if end >= 0 else len(text)].strip().replace("\n", " ")


def _extract_rules(text: str) -> list[dict]:
    events: list[dict] = []

    m = re.search(r"capped\s+at\s+([\d,]+)\s+units\s+per\s+week.*?first\s+"
                  r"(\w+)\s+weeks\s+of\s+next\s+quarter", text,
                  re.IGNORECASE | re.DOTALL)
    if m and _word_num(m.group(2)) is not None:
        # scope the variant scan to the cap sentence and the one before it,
        # not the whole message (a distant "V1 is unaffected" must not drag
        # V1 into the cap) — a stand-in heuristic; the LLM backend handles
        # scoping semantically and sanitize() bounds the blast radius
        evidence = _sentence_of(text, m.start())
        sentences = [s for s in text[:m.end()].split(".") if s.strip()]
        scope = ". ".join(sentences[-2:])
        variants = sorted(set(re.findall(r"Variant V\d+", scope)))
        events.append({
            "event_type": "supply_cap",
            "params": {"variants": variants, "start_offset": 0,
                       "n_weeks": _word_num(m.group(2)),
                       "weekly_cap": float(m.group(1).replace(",", ""))},
            "evidence": evidence, "confidence": 1.0})

    m = re.search(r"(Retailer R\d)\b.*?double\s+their\s+Q4\s+order\s+volume"
                  r"\s+on\s+(Variant V\d+)", text, re.IGNORECASE | re.DOTALL)
    if m and m.group(1) in G1_RETAILERS:
        events.append({
            "event_type": "demand_shock",
            "params": {"variant": m.group(2), "geo": "Geo G1",
                       "start_offset": 0, "n_weeks": 13, "multiplier": 2.0},
            "evidence": _sentence_of(text, m.start()), "confidence": 1.0})

    m = re.search(r"(Fast Boat Ocean|Standard Ocean|Ground|Air)\s+service\s+"
                  r"to\s+(Geo G\d)\s+will\s+be\s+suspended\s+for\s+(\w+)\s+"
                  r"weeks\s+starting\s+(\d{4}W\d{2})", text, re.IGNORECASE)
    if m and _word_num(m.group(3)) is not None:
        events.append({
            "event_type": "freight_disruption",
            "params": {"geo": m.group(2), "mode": m.group(1),
                       "start_offset": _n(m.group(4)),
                       "n_weeks": _word_num(m.group(3))},
            "evidence": _sentence_of(text, m.start()), "confidence": 1.0})

    m = re.search(r"a\s+(\d+)%\s+uplift\s+for\s+core\s+variants\s+"
                  r"(?:in\s+(Geo G\d)\s+)?during\s+(\d{4}W\d{2})\s*[-–]\s*"
                  r"(\d{4}W\d{2})", text, re.IGNORECASE)
    if m:
        geo = m.group(2)
        start = _n(m.group(3))
        n_weeks = _n(m.group(4)) - start + 1
        for variant in CORE_VARIANTS:
            events.append({
                "event_type": "demand_shock",
                "params": {"variant": variant, "geo": geo,
                           "start_offset": start, "n_weeks": n_weeks,
                           "multiplier": 1 + int(m.group(1)) / 100},
                "evidence": _sentence_of(text, m.start()), "confidence": 1.0})

    return events


G1_RETAILERS = {"Retailer R1", "Retailer R2", "Retailer R3", "Retailer R4"}


# ---------------- claude backend ----------------

def _extract_claude(text: str) -> list[dict]:
    import anthropic                       # lazy: optional dependency

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1500,
        system=CLAUDE_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    blocks = [b.text for b in msg.content if getattr(b, "type", "") == "text"]
    raw = re.sub(r"^```(?:json)?|```$", "", "\n".join(blocks).strip(),
                 flags=re.MULTILINE).strip()
    out = []
    for e in json.loads(raw):
        out.append({
            "event_type": e.get("event_type"),
            "params": {k: v for k, v in e.items()
                       if k not in ("event_type", "evidence", "confidence")},
            "evidence": str(e.get("evidence", ""))[:500],
            "confidence": e.get("confidence", 0.0)})
    return out
