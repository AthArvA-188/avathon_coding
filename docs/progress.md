# Progress — Program Z Planner

Running log. Newest phase status at top of each section; check items off as they land.

## Phase status

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Planning: data audit, decisions, PRD, repo setup | ✅ Done (2026-08-21) |
| 1 | Ingestion: xlsx → SQLite, fiscal calendar, tests | ✅ Done (2026-08-21) |
| 2 | Forecast: features, baselines, XGBoost quantiles, lifecycle, holdout scoring | ✅ Done (2026-08-21) |
| 3 | MPS: MILP, pack-out, freight, WOS, constraint validators | ✅ Done (2026-08-21) |
| 4 | Scenario: V2+V4 shared cap, allocation, diff computation | ✅ Done (2026-08-21) |
| 5 | UI: forecast explorer, MPS view, scenario toggle + diff | ✅ Done (2026-08-21) |
| 6 | Packaging: deck (HTML), README, start scripts, cover note | ⬜ Not started |

## Phase 0 — Planning ✅ (2026-08-21)

- [x] Read brief; audited all 5 sheets of `program_z.xlsx`
- [x] Established data facts: actuals 2021W41→2023W39 (104 wks); horizon 2023W40→2024W39; fiscal calendar (FY ≈ Oct–Sep); shortage window 2023W40–W45 (≈ Jul–Aug, the pre-holiday build window); V10/V11 are zero-history NPIs; 218 negative cells; freight table has gaps
- [x] Decisions D1–D19 recorded in `decisions.md` (stack/architecture/solver/uncertainty confirmed by owner)
- [x] PRD written; docs folder created
- [x] Git repo initialized; planning commit pushed to `github.com/AthArvA-188/avathon_coding`

## Phase 1 — Ingestion ✅ (2026-08-21)

- [x] `engine/` scaffold on conda env `avathon` (Python 3.12; numpy 2.5 / pandas 3.0 / xgboost 3.4 / pulp 3.3)
- [x] Fiscal calendar module (53-week fiscal 2021 with 14-week Q1) + calendar table, unit-tested against seasonality-sheet ground truth
- [x] Parse 5 sheets → normalized SQLite tables (154 series, 32,032 actuals, 2,199 weekly prices, 52 seasonality rows, 12 variants)
- [x] Weekly price pipeline: $0 placeholders dropped, day-mean-first (duplicate 2022-02-28 extract rows), span-bounded peer fill + sole-carrier carry-forward (`is_filled` 0/1/2, 127 fills) — D21
- [x] Atomic single-transaction ingest (failed run leaves previous DB intact); idempotent (double-run test)
- [x] Adversarial review workflow (7 agents): 2 confirmed HIGH test gaps + 18 advisories; fill fabrication, duplicate-date weighting, atomicity, and all test-coverage gaps fixed
- [x] 23 tests green: calendar vs seasonality ground truth, full-series-grain totals reconciled to xlsx, price values vs independent recomputation, params/freight full double-entry, quirks (D20–D22)

## Phase 2 — Forecast ✅ (2026-08-21)

- [x] FeatureBuilder: lags (incl. label-based YoY across the 53-wk 2021), rolling stats, 8 holiday-group flags ± adjacency, relative price index (known-ahead to 2024W27), lifecycle features
- [x] Scoring harness (WAPE/sMAPE/bias/pinball) + baselines; recursive 13-wk holdout backtest
- [x] XGBoost P10/P50/P90 on log1p target with volume weights: **37.6% WAPE / +3.3% bias vs seasonal-naive 50.7%** (experiment log in D9); weak spots documented (V5/V6/V9 lumpy deals, G3)
- [x] NPI analog ramps ×seasonal index for V10/V11 (exact deal volumes); EOL zero V12; D23 forward-volume caps enforced (V5 exhausts 2023W51, V7 2024W10, V6 2024W21)
- [x] Production forecast: 124 series × 52 wks; horizon P50 total **952,865 units vs 896,000 annual capacity** → structurally supply-constrained year (headline for deck)
- [x] 33 tests green (metrics hand-checks, cap clipping, NPI totals, integration incl. must-beat-baseline gate)

## Phase 3 — MPS ✅ (2026-08-21)

- [x] Run-out WOS calculator + tests (spiky-demand cases)
- [x] MILP (PuLP/CBC, 44 s): production/pack-out binaries, weekly+quarterly caps, ≤4 slots, two-tier inventory (supply position 12 WOS, channel 13 WOS), D23 volume caps, scenario hook — D25
- [x] Freight per D12: cheapest feasible per geo + Air expedite; result: $5.13M ($4.37M Air = the price of capacity scarcity)
- [x] Independent validators (7 checks) + tests proving each catches its violation; plan tables written (`mps`, `shipments`, `inventory`, `validation`)
- [x] Adversarial review round 2 (6 agents, mutation-tested): 3 confirmed HIGH test gaps (no MILP solve in suite — a zero-production plan passed all validators; accuracy asserted only as ordering; NPI shape untested) + 16 advisories. Fixed: MILP smoke-solve test, absolute score bands, NPI shape pins, Fast Boat added to the freight frontier, no-phantom-shipment rule, NPI analog deseasonalization, balance-replay + shorts validators, non-destructive plan-scoped schema, negative-index guard
- [x] Baseline (post-review): 846,991 u produced (94.5% of capacity, 3 quarters at cap), **0 u unmet**, freight $5.22M ($4.68M Air), 9/9 validators
- [x] 48 tests green (~20 s incl. reduced-universe MILP smoke solve)
- [x] Progress artifact published & updated (charts: forecast, accuracy, capacity crunch)

## Phase 4 — Scenario ✅ (2026-08-21)

- [x] Re-solve with V2+V4 ≤ 4,500/wk (2023W40–W45) via the `extra_prod_caps` hook; 35 s, all validators PASS incl. the shared-cap check
- [x] Allocation observed (D13): alternating full-cap weeks → exact 50/50 split (13,500 u each), batching to preserve pack-out slots
- [x] Diff summary: volume −346 u, freight ≈ flat (−$76k, within solver gap), unmet +2 u, V2+V4 supply position trails baseline through **2024W29** (~8-month recovery tail), Ch3 drift + per-geo WOS impact computed
- [x] Both plans coexist plan-scoped in the same tables (`scenario_diff` table dropped as redundant — the UI diffs the two plan_ids directly)
- [x] 51 tests green (reduced-universe scenario solve: cap binds in-window, catch-up beyond, baseline untouched)

## Phase 5 — UI ✅ (2026-08-21)

- [x] Next.js 16 (App Router, TS, Tailwind) + better-sqlite3 read-only data layer + 4 JSON API routes (`/api/meta|forecast|plan|scenario`)
- [x] Forecast explorer: variant/geo/channel filters, actuals + P50 with P10/P90 band, holdout accuracy panel per selection
- [x] MPS view: weekly production vs 17,280 cap, full 52×11 pack-out grid with slot counts, freight by geo×mode, WOS trajectories vs 12/13 targets, validator status
- [x] Scenario view: instant toggle (both plans pre-solved), delta stats, allocation table, V2+V4 production + supply-position recovery charts, stockouts & per-geo WOS impact
- [x] Verified: production build clean; all 4 APIs + 4 pages smoke-tested live (200s, correct shapes)

## Phase 6 — Packaging

- [ ] `start.ps1` / `start.sh`; README (prereqs, setup, ingest, launch, code map, limitations)
- [ ] HTML slide deck (~12–16 slides) incl. §3.4 next-gen threads
- [ ] Final pass: commit history, cover note draft

## Notes / blockers

- gh CLI absent — remote managed via plain git + owner-created repo (resolved).
- ECC fact-gate hook fires on first creation of every file; workflow accounts for it.
