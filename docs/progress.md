# Progress — Program Z Planner

Running log. Newest phase status at top of each section; check items off as they land.

## Phase status

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Planning: data audit, decisions, PRD, repo setup | ✅ Done (2026-08-21) |
| 1 | Ingestion: xlsx → SQLite, fiscal calendar, tests | ✅ Done (2026-08-21) |
| 2 | Forecast: features, baselines, XGBoost quantiles, lifecycle, holdout scoring | ✅ Done (2026-08-21) |
| 3 | MPS: MILP, pack-out, freight, WOS, constraint validators | ⬜ Not started |
| 4 | Scenario: V2+V4 shared cap, allocation, diff computation | ⬜ Not started |
| 5 | UI: forecast explorer, MPS view, scenario toggle + diff | ⬜ Not started |
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

## Phase 3 — MPS

- [ ] WOS calculator (run-out method) + tests
- [ ] MILP: production/pack-out vars, caps, ≤4 pack-out slots, WOS penalties, freight costs
- [ ] Independent constraint validator + tests
- [ ] Freight mode assignment per D12; capacity utilization outputs
- [ ] Write `mps_baseline` tables

## Phase 4 — Scenario

- [ ] Re-solve with V2+V4 ≤ 4,500/wk (2023W40–W45); allocation per D13
- [ ] Diff computation: volume Δ, freight cost Δ, WOS violations by geo, stockout weeks by SKU, pack-out slot changes, recovery curve
- [ ] Write `mps_scenario` + `scenario_diff` tables; tests on the shared-cap validator

## Phase 5 — UI

- [ ] Next.js scaffold, better-sqlite3 data layer, API routes
- [ ] Forecast explorer (filters, interval shading, accuracy panel)
- [ ] MPS view (pack-out grid, utilization, freight, WOS trajectories)
- [ ] Scenario toggle + side-by-side diff view

## Phase 6 — Packaging

- [ ] `start.ps1` / `start.sh`; README (prereqs, setup, ingest, launch, code map, limitations)
- [ ] HTML slide deck (~12–16 slides) incl. §3.4 next-gen threads
- [ ] Final pass: commit history, cover note draft

## Notes / blockers

- gh CLI absent — remote managed via plain git + owner-created repo (resolved).
- ECC fact-gate hook fires on first creation of every file; workflow accounts for it.
