# PRD — Program Z Demand Planning Mini-Application

**Status:** Approved (planning phase) · **Owner:** Sigma Health Sense team · **Last updated:** 2026-08-21

## 1. Overview

A runnable demand-planning application for **Program Z**, a premium wearable shipped through global retail channels. The app ingests `program_z.xlsx` (immutable input), produces a 4-quarter weekly demand forecast, derives a Master Production Schedule (MPS) + pack-out plan that respects all hard constraints, and lets a planner toggle a V2+V4 enclosure-shortage scenario and inspect the diff against baseline.

Source brief: [`ASSIGNMENT.md`](../ASSIGNMENT.md). This PRD translates it into concrete, testable requirements.

## 2. Users

| User | Needs |
| --- | --- |
| **Planner** (primary) | Inspect forecast by SKU/Geo/Channel/week, review the weekly MPS + pack-out schedule, toggle the shortage scenario, understand freight choices and WOS positions. |
| **Planning lead** (reviewer) | Judge forecast quality, constraint compliance, and trade-off reasoning from the slide deck without reading code. |
| **Engineer (non-author)** | Clone, set up, ingest, and launch with one command each; re-run as inputs evolve. |

## 3. Problem statements (from the brief)

1. **Forecast** — What does demand (`Net Sell-Through`) look like over the next 4 quarters (2023W40 → 2024W39, fiscal weeks) at SKU × Geo × Channel × Week grain?
2. **MPS + pack-out** — What weekly production/pack-out plan supports that demand while hitting WOS targets (12 WOS Kanban+Sea Freight, 13 WOS channel) and respecting the weekly cap (17,280 u), quarterly cap (224,000 u), and the ≤4-variants-packed-per-week rule?
3. **Shortage scenario** — With V2+V4 combined supply capped at 4,500 u/week for the first 6 weeks of CQ+1 (2023W40–2023W45, ≈ Jul–Aug — the pre-holiday build window: ocean shipments from these weeks arrive just as the holiday quarter starts), how does the plan change, how is scarce supply allocated, and what is the downstream impact?

Additionally (deck-only, prototype optional): a point of view on foundation forecasting models, LLM-augmented signals, agentic planning loops, and conversational planner UX (§3.4 of the brief).

## 4. Functional requirements

### F1 — Ingestion
- F1.1 One command reads `program_z.xlsx` and materializes a normalized SQLite database (`planz.db`). The xlsx is never modified.
- F1.2 Ingestion parses all 5 sheets: actuals (long format: series × week × metric), pricing (daily → weekly per retailer × variant), seasonality calendar (event × fiscal week), variant details (classification, release week, lifetime caps), objective parameters (WOS targets, freight table, caps).
- F1.3 The fiscal week calendar (fiscal year ≈ Oct–Sep; week labels like `2023W40`) is materialized as a lookup table mapping fiscal week → fiscal quarter → approximate calendar date.
- F1.4 Ingestion is idempotent: re-running rebuilds the DB deterministically.

### F2 — Forecast engine
- F2.1 Produces `Net Sell-Through` forecasts for every active SKU × Geo × Channel series, weekly, 2023W40 → 2024W39 (52 weeks).
- F2.2 XGBoost quantile models (P10/P50/P90) trained on lag/rolling/price/holiday/lifecycle features; scored against seasonal-naive and naive baselines on a 13-week holdout (2023W27–2023W39). Metrics: WAPE, sMAPE, bias, pinball loss — persisted to the DB.
- F2.3 Holiday/promo weeks are explicit features (the seasonality calendar), not left to the model to infer.
- F2.4 Lifecycle handling: NPI ramp curves for V10/V11 (release 2023W49, zero history — analog curves from V8/V9 scaled by lifetime volume); EOL zero-forecast for V12; lifetime-volume caps enforced for all exclusives and one-time-deals (cumulative actuals + forecast ≤ cap; violation is a build error).
- F2.5 Output: a forecast table a downstream planner (and the MPS solver) consumes directly.

### F3 — MPS + pack-out engine
- F3.1 MILP (PuLP + CBC) computes a weekly MPS per variant over 4 quarters with hard constraints: weekly cap 17,280; quarterly cap 224,000; ≤4 variants packed out per week; non-negative inventories.
- F3.2 WOS targets (12 Kanban+Sea, 13 channel) enter the objective as deviation penalties; freight cost enters per chosen mode; the solve must be feasible and every hard constraint machine-validated post-solve (independent validator, not the solver's own status).
- F3.3 Freight mode per Geo chosen from the Objective sheet's table (Air/Ground/Fast Boat/Standard Ocean with lead times and unit costs); gaps in the table are filled by documented assumptions (see decisions.md D12).
- F3.4 Outputs: weekly pack-out schedule, production quantities, freight mode + cost per Geo, projected inventory and WOS per SKU × Geo, capacity utilization per week/quarter.

### F4 — Shortage scenario
- F4.1 Re-runs the MPS with the additional constraint: V2+V4 combined ≤ 4,500 u/week for 2023W40–2023W45.
- F4.2 The allocation of scarce supply across V2/V4 follows a documented rule (decisions.md D13) and is visible in the output.
- F4.3 Scenario results are persisted alongside baseline; the diff (volume delta, freight cost delta, WOS violations per Geo, stockout-week count per SKU, pack-out slot changes, recovery curve) is queryable.

### F5 — UI (Next.js)
- F5.1 **Forecast explorer**: chart + table of actuals and P10/P50/P90 forecast, filterable by SKU, Geo, Channel; holdout accuracy panel (model vs baselines).
- F5.2 **MPS view**: week-by-week pack-out schedule (which 4 variants), production quantities, capacity utilization vs caps, freight mode/cost per Geo, WOS trajectory per SKU.
- F5.3 **Scenario view**: a toggle switches baseline ↔ shortage plan and renders the side-by-side diff of F4.3. Toggling requires no Python re-run (both plans precomputed).
- F5.4 UI is functional and self-explanatory; aesthetics are secondary.

### F6 — Operability
- F6.1 One command to set up (`start.ps1` / `start.sh`), one to ingest+compute (`python engine/run_pipeline.py`), one to launch the UI.
- F6.2 `README.md` covers prerequisites, setup, ingest, launch, code map, limitations.
- F6.3 Tests (pytest) cover, at minimum: forecast scoring harness, capacity/pack-out constraint validation, WOS calculation, lifetime-cap enforcement.

## 5. Non-functional requirements

- **Reproducibility:** fixed random seeds; pipeline re-runs give identical outputs from identical inputs.
- **Performance:** full pipeline (ingest → forecast → 2 MILP solves) completes in minutes on a laptop; UI queries answer in <1 s from SQLite.
- **Auditability:** every constraint has an independent validator; every assumption is logged in `docs/decisions.md` and surfaced in the deck.
- **Commit hygiene:** incremental commits per phase (the brief treats a single squashed commit as a negative signal).

## 6. Deliverables

1. Runnable app (this repo).
2. Slide deck: **self-contained HTML** in `deck/` (~12–16 slides, printable to PDF).
3. Source code with README, tests, and honest commit history.
4. Cover note (≤300 words) at submission time.

## 7. Success criteria

- Forecast beats seasonal-naive on WAPE over the 13-week holdout for the major series (G1 core variants), with honest reporting where it doesn't.
- Zero hard-constraint violations in both baseline and scenario plans (machine-verified).
- Scenario toggle works end-to-end in the UI and the diff answers every bullet in brief §3.3.
- A non-author can go from clone to running UI with the documented commands.

## 8. Out of scope

- Managed databases, auth, deployment infra (local-only app).
- Prototyping more than one §3.4 next-gen thread (deck coverage of all four is in scope; at most one prototype if time allows).
- Forecasting `Sell-In` directly (derived from sell-through + channel inventory policy instead; see decisions.md D18).

## 9. Risks & open questions (to raise with the client)

- Freight table is an incomplete matrix (no ocean option for G3/G5, no ground outside G4) — filled with documented assumptions.
- The brief says actuals end 2023W26, but the file contains actuals through **2023W39**; we follow the file.
- Negative sell-through weeks (returns) — handling per decisions.md D8.
- WOS definition (run-out vs fixed-window) — per decisions.md D11; sensitivity discussed in deck.
- Pricing covers only 7 SKUs at 4 G1 retailers — price features apply only where coverage exists.
