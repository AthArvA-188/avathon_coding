# Program Z — Demand Planning Mini-Application

Take-home submission: a runnable planning system for a premium wearable —
4-quarter demand forecast (SKU × geo × channel × week), a capacity-feasible
MPS + pack-out plan, and the V2+V4 enclosure-shortage scenario with a
side-by-side diff.

**Stack:** Python 3.12 (XGBoost quantile forecasting, PuLP/CBC MILP planning)
→ SQLite (`planz.db`) → Next.js UI. The xlsx is immutable input; every stage is
atomic, idempotent, and independently validated.

## Quick start

Prerequisites: [Miniconda](https://docs.conda.io/en/latest/miniconda.html) and Node.js 18+.

**One command:**

```bash
./start.sh          # macOS / Linux / Git Bash
./start.ps1         # Windows PowerShell
```

That creates the `avathon` conda env, installs deps, runs the full pipeline
(ingest → forecast → MPS → scenario, ~2 min), and serves the UI at
http://localhost:3000.

**Or step by step:**

```bash
conda create -n avathon python=3.12 -y && conda activate avathon
pip install -r engine/requirements.txt

python engine/run_pipeline.py --all        # or --ingest --forecast --mps --scenario
python engine/run_pipeline.py --signals    # §3.4: extract events from the inbox + eval
python engine/run_pipeline.py --agents     # §3.4: run the agentic planning loop

cd engine && python -m pytest tests -q     # 66 tests, ~30 s
python engine/verify.py                    # 14 independent spot checks

cd ../app && npm install && npm run dev    # UI on http://localhost:3000
```

## What you're looking at

| Where | What |
| --- | --- |
| `deck/slides.html` | **The slide deck** — open in any browser (←/→ to navigate, Ctrl+P for PDF) |
| `engine/planz/ingest.py` | xlsx → SQLite, atomic, with data-quirk handling |
| `engine/planz/calendar.py` | Fiscal week calendar (53-week FY2021 with a 14-week Q1) |
| `engine/planz/features.py` + `forecast.py` | Feature builder + XGBoost P10/P50/P90 with recursive 52-week prediction and holdout backtest |
| `engine/planz/lifecycle.py` | NPI analog launch ramps (V10/V11), EOL, volume-cap enforcement |
| `engine/planz/mps.py` + `wos.py` | MILP (weekly/quarterly caps, ≤4 pack-out slots, two-tier WOS inventory, freight frontier) + run-out WOS |
| `engine/planz/heuristic.py` | The second planning method: a transparent greedy plan, same validators — run `--heuristic` for the head-to-head vs the MILP |
| `engine/planz/validate.py` | 9 independent post-solve constraint checks — the pipeline fails on any violation |
| `engine/planz/scenario.py` | V2+V4 shared-cap re-solve + baseline diff |
| `engine/planz/llm.py` + `signals.py` | **§3.4 prototype:** unstructured inbox → typed events with provenance, human approval gate, eval harness (Claude backend if `ANTHROPIC_API_KEY` is set, offline rules backend otherwise) — run `--signals` |
| `engine/planz/agents.py` | **§3.4 prototype:** agentic loop — signal extraction → approval → greedy-first proposal → verifier (constraints + service policy) → escalate to MILP → publish or `needs_human`, fully logged in `agent_log` — run `--agents` |
| `engine/verify.py` | Human-friendly auditor: 14 checks sharing no code with the pipeline |
| `engine/tests/` | 66 pytest tests (calendar ground truth, xlsx reconciliation, score bands, MILP smoke solve, validator mutations, signal sanitization, agent-loop gates) |
| `app/` | Next.js UI: forecast explorer, MPS & pack-out view, scenario toggle, signals page (decoded events + approval status), agents audit trail — every page opens with a "where these numbers come from" provenance strip |
| `app/app/planner/` | **§3.4 prototype:** "Ask the Planner" — voice (Web Speech API) or text → claude-sonnet-5 intent parser (regex fallback offline) → whitelisted SQL with the executed statements shown; what-ifs become gated signal events, never chat-side edits |
| `docs/` | PRD, decision log (D1–D29 with options + rationale), progress log, technical documentation |

## Headline results

- Holdout forecast (13 hidden weeks): **37.6% WAPE / +3.3% bias** vs
  seasonal-naive 50.7% and naive 89.1%.
- Horizon demand **952,865 u vs 896,000 u annual capacity** — the holiday
  quarter alone wants 2× the quarterly cap, so the plan pre-builds and runs
  3 of 4 quarters at exactly 224,000 u.
- Baseline plan: **846,991 u, zero unmet demand, $5.22M freight** — of which
  $4.68M is air expedite, effectively the price of the missing capacity.
- Shortage scenario: only −346 u of volume lost, but the V2+V4 supply position
  **trails baseline until 2024W29** — a 6-week shortage leaves an ~8-month scar.
- Two planning methods, one verdict: the greedy heuristic is cheaper ($4.62M
  freight) and simpler, but leaves **99,455 u unmet vs the MILP's 0** — the
  measured price of skipping cross-week lookahead in a capacity-starved year.

## Known limitations

- Opening inventory is assumed at the client's stated policy targets (no
  opening position in the data) — docs/decisions.md D24.
- Exclusive "lifetime volumes" are read as *forward* volumes (V8 already sold
  2.4× its stated number) — D23, flagged as a client question.
- The air-freight headline is sensitive to the supply-WOS penalty weight
  (a policy dial, not physics) — D25.
- Forecast is honest-but-weak on lumpy single-retailer deal variants
  (V5/V6/V9); they are small and volume-capped.
- The UI is read-only by design: re-planning = re-running the pipeline.

Every decision, with the options considered, lives in
[`docs/decisions.md`](docs/decisions.md); the phase-by-phase build log in
[`docs/progress.md`](docs/progress.md); data dictionary and schemas in
[`docs/documentation.md`](docs/documentation.md); and the ten big decisions as
rehearsable 30-second stories in
[`docs/talking-points.md`](docs/talking-points.md).
