# Progress — Program Z Planner

Running log. Newest phase status at top of each section; check items off as they land.

## Phase status

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Planning: data audit, decisions, PRD, repo setup | ✅ Done (2026-08-21) |
| 1 | Ingestion: xlsx → SQLite, fiscal calendar, tests | ⬜ Not started |
| 2 | Forecast: features, baselines, XGBoost quantiles, lifecycle, holdout scoring | ⬜ Not started |
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

## Phase 1 — Ingestion (next)

- [ ] `engine/` scaffold: venv, `requirements.txt`, package layout per `documentation.md`
- [ ] Fiscal calendar module + lookup table (week ↔ quarter ↔ date), unit-tested
- [ ] Parse 5 sheets → normalized SQLite tables (schema in `documentation.md`)
- [ ] Weekly price aggregation + peer-fill rule for missing retailer prices
- [ ] Idempotent `python engine/run_pipeline.py --ingest`
- [ ] Tests: calendar mapping, row counts, series totals reconcile to xlsx

## Phase 2 — Forecast

- [ ] Feature builder (lags, rolling stats, holiday flags, price index, lifecycle features)
- [ ] Baselines: naive, seasonal-naive; scoring harness (WAPE/sMAPE/bias/pinball) + tests
- [ ] XGBoost P10/P50/P90 on 13-wk holdout (2023W27–W39); beat-or-explain vs baselines
- [ ] NPI analog ramps (V10/V11), EOL zero (V12), lifetime-cap enforcement + tests
- [ ] Refit on full history; write `forecast` table

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
