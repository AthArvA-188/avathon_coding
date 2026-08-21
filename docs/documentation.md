# Technical Documentation — Program Z Planner

Living document: data dictionary, architecture, module map, DB schema. Updated as each phase lands.

## 1. Input data — `program_z.xlsx` (immutable)

Five sheets. All week labels in the workbook are **fiscal weeks**, not ISO calendar weeks.

### 1.1 Fiscal calendar

- Fiscal year runs ≈ **October → September** (e.g. fiscal 2022 ≈ Oct 2021 – Sep 2022).
- Evidence: pricing date 2021-07-20 maps to `YEAR_WEEK` 202143; Black Friday sits at fiscal week ~09 (late Nov); XMAS at fiscal week 13–14 (late Dec); Mother's Day at fiscal Q3 week 6 (May).
- Quarters: Q1 = W01–W13 (the holiday quarter: Black Friday, XMAS), Q2 = W14–W26, Q3 = W27–W39, Q4 = W40–W52 — **except fiscal 2021, a 53-week year with a 14-week Q1** (boundaries W14/W27/W40/W53; see §6). Label year increments at W01. The label↔quarter mapping is materialized in the `calendar` table by ingest and unit-tested against the Strong Seasonality Weeks sheet (`CY_Qtr_Wk` ground truth like `2023_Q1_09`).

### 1.2 Sheets

**Pricing Data** — 13,802 data rows × 6 cols. Columns: `Price` (float, USD), `Retailer` (R1–R4), `Date` (datetime, daily, from 2021-07-20), `PPN` (zero-padded part number `0001`…), `Variant` (`Variant V1`…), `YEAR_WEEK` (fiscal, e.g. `202143`). Covers only top-4 Geo G1 retailers and 7 SKUs. Missing retailer-week prices are peer-filled (Objective rule).

**Strong Seasonality Weeks** — 13 events × 4 fiscal years (2021–2024). Two header rows; per year: `CY_Qtr_Wk` (`2023_Q1_09`) and `CY_Wk` (`2023_09`). Events: Promo Q1 (+rollover), Black Friday, Cyber Monday, Pre-XMAS W1/W2, XMAS, Mother's Day W1/W2, Father's Day W1/W2, Promo Q4 (x2).

**Variant Details** — 12 variants. Columns: `Part Number` (1–12), `Variant`, `Core/Exclusive` (classification incl. lifetime volume for one-time-deals), `Notes` (release fiscal week for exclusives), `Geo G1`/`Geo G2`/`Geo G3-5` (exclusive lifetime volumes).

| Variant | Class | Release | Lifetime cap |
| --- | --- | --- | --- |
| V1–V4 | Core | pre-history | — |
| V5 | One Time Deal (R4) | pre-history | 38,000 |
| V6 | One Time Deal (R4) | pre-history | 50,000 |
| V7 | One Time Deal (R4) | pre-history | 22,000 |
| V8 | R3 Exclusive | 2023W02 | 13,832 (G1) |
| V9 | R4 Exclusive | 2022W48 | 20,058 (G1) |
| V10 | R2 Exclusive | **2023W49** (in horizon) | 55,332 G1 + 2,075 G2 |
| V11 | R4 Exclusive | **2023W49** (in horizon) | 19,020 G1 + 3,458 G2 + 1,211 G3-5 |
| V12 | One-time drop | sold out 2022W14 | <1,000 |

**Data - 104 weeks** — 308 rows (154 series × 2 metrics) × 156 fiscal-week columns `2021W41 … 2024W39`. ID columns: `Channel Level 2 Desc.` (Channel 1/2/3), `Geo Level 1 Desc.` (G1–G5), `Customer Sold To Desc.` (Retailer R1–R4, Rest of Geo G1, Rest of World), `PPN`, `Variant Desc.`, `SKU` (e.g. `G1_0001`), `Values` (`Net Sell-Through` | `Sell-In (Billings)`). Actuals fill **2021W41 → 2023W39** (104 weeks); **2023W40 → 2024W39** (52 weeks) is the blank forecast window. 218 negative cells (returns). Volume mix: G1 ≈ 90% (1.40 M of 1.56 M units ST).

**Objective** — planning brief text. Machine-relevant parameters:

| Parameter | Value |
| --- | --- |
| Kanban buffer | 6 WOS |
| Sea freight buffer | 6 WOS |
| Reseller (Ch3) inventory | 13 WOS |
| Target | 12 WOS (Kanban+Sea) and 13 WOS channel, all SKUs |
| OEM | Thailand |
| Weekly capacity cap | 17,280 u |
| Quarterly capacity cap | 224,000 u |
| Pack-out rule | ≤ 4 variants packed out per week |
| Freight | Air 1wk $7/u (any geo); Ground 1wk $2.5 (G4); Fast Boat 5wk $3.5 (G1); Std Ocean 8wk $2 (G1); Std Ocean 11wk $2.5 (G2) |
| Scenario | V2+V4 combined ≤ 4,500 u/wk, first 6 wks of CQ+1 → **2023W40–2023W45** |
| Channel identity | Ch1 & Ch2: Sell-In = Sell-Through |

## 2. Architecture

```
program_z.xlsx ──> engine/ (Python 3.13)                    app/ (Next.js)
                   ├─ ingest      ─┐                        ├─ /forecast   (explorer)
                   ├─ forecast     ├──> planz.db (SQLite) ──┤─ /mps        (plan view)
                   ├─ mps (MILP)   │      ^ read-only       └─ /scenario   (toggle + diff)
                   └─ scenario    ─┘      └ better-sqlite3
                   run_pipeline.py (CLI orchestrator)
deck/  self-contained HTML slides
docs/  PRD, decisions, progress, this file
```

Batch pipeline computes everything (baseline + scenario) up front; the UI is a pure reader. Re-planning = re-running the CLI.

## 3. Planned repository layout

```
avathon_coding/
├── ASSIGNMENT.md               # brief (as received)
├── program_z.xlsx              # immutable input
├── README.md
├── start.ps1 / start.sh        # one-command setup
├── docs/                       # PRD.md, decisions.md, progress.md, documentation.md
├── engine/
│   ├── requirements.txt
│   ├── run_pipeline.py         # CLI: --ingest --forecast --mps --scenario --all
│   ├── planz/
│   │   ├── calendar.py         # fiscal week mapping
│   │   ├── ingest.py           # xlsx -> SQLite
│   │   ├── features.py         # lags, rolling, holiday, price features
│   │   ├── forecast.py         # baselines + XGBoost P10/P50/P90
│   │   ├── lifecycle.py        # NPI ramps, EOL, lifetime caps
│   │   ├── wos.py              # run-out WOS calculator
│   │   ├── mps.py              # PuLP MILP + freight assignment
│   │   ├── validate.py         # independent constraint validators
│   │   ├── scenario.py         # V2+V4 shared-cap re-solve + diff
│   │   └── db.py               # schema, writers, readers
│   └── tests/
├── app/                        # Next.js (App Router, TS, Tailwind, Recharts)
└── deck/                       # HTML slide deck
```

## 4. SQLite schema (draft — finalized in Phase 1)

- `calendar(week_label PK, fiscal_year, fiscal_qtr, fiscal_week, week_index, approx_date)`
- `series(series_id PK, channel, geo, customer, ppn, variant, sku)`
- `actuals(series_id, week_label, metric, units)` — long format, negatives preserved
- `prices(retailer, variant, week_label, price, filled_flag)` — weekly, peer-filled
- `seasonality(event, fiscal_year, week_label)`
- `variants(variant PK, class, exclusive_retailer, release_week, cap_g1, cap_g2, cap_g35)`
- `params(key PK, value)` — WOS targets, caps, scenario constants
- `freight(mode, geo, lead_time_wks, cost_per_unit)`
- `forecast(variant, geo, channel, week_label, p10, p50, p90, method)` — method ∈ {xgb, npi_ramp, eol_zero}
- `forecast_scores(variant, geo, channel, model, wape, smape, bias, pinball10, pinball90)`
- `mps(plan_id, variant, week_label, production, packout_flag, geo, shipped, freight_mode, freight_cost)` — plan_id ∈ {baseline, scenario}
- `inventory(plan_id, variant, geo, week_label, kanban_sea_units, channel_units, wos_kanban_sea, wos_channel)`
- `scenario_diff(variant, geo, week_label, metric, baseline_value, scenario_value)`
- `validation(plan_id, check_name, status, detail)`

## 5. Modelling notes (to be expanded per phase)

- **Target:** weekly `Net Sell-Through`, negatives clipped to 0 for training (D8); grain SKU × Geo × Channel (D7).
- **Features:** lags {1,2,4,13,52}, rolling means/max {4,13}, holiday event one-hots ± lead/lag weeks, weekly price level & discount-vs-median for priced SKUs, weeks-since-release, class one-hots, geo/channel encodings.
- **Backtest:** train ≤ 2023W26, score 2023W27–W39 vs naive & seasonal-naive; refit on all 104 wks for production forecast (D9).
- **MPS mechanics (implemented, D25):** decision vars = weekly production per variant, pack-out binaries (≤4/week), shipments per variant×geo×mode (cheapest feasible mode + Air expedite), two-tier inventories (DC on-hand + in-transit vs 12-WOS target; Channel-3 stock vs 13-WOS target; Ch1/2 SI=ST direct). Hard: weekly 17,280 / quarterly 224,000, slots, balances, non-negativity, D23 volume caps. Objective: shortage ≫ WOS deviations > freight > holding. WOS targets linearized as next-12/13-week demand sums (run-out convention); demand beyond the horizon padded with the same fiscal weeks one year earlier. Post-solve, `validate.py` independently re-checks every hard constraint and writes the `validation` table; the pipeline fails on any FAIL.
- **Scenario (phase 4):** identical model + per-week combined cap `prod[V2,w] + prod[V4,w] ≤ 4500` for w ∈ 2023W40–W45 via the `extra_prod_caps` hook; allocation emerges from WOS-equalizing objective (D13) and is reported explicitly.

## 6. How to run

```bash
# one-time environment (conda)
conda create -n avathon python=3.12 -y
conda activate avathon
pip install -r engine/requirements.txt

# ingest xlsx -> planz.db (repo root)
python engine/run_pipeline.py --ingest

# tests
cd engine && python -m pytest tests -q
```

Later stages: `--forecast`, `--mps`, `--scenario`, or `--all` (stubs until their phases land). `start.ps1`/`start.sh` wrappers arrive in Phase 6.

### Data quirks found during ingest (Phase 1)

| Quirk | Handling |
| --- | --- |
| 4 Ch3/G2 series duplicated under a tiny `Region 2_` SKU bucket with blank PPN (54 units lifetime total) | Kept as separate series; PPN derived from variant number; series key includes SKU (D20) |
| 168 daily prices of exactly $0 (Retailer R2, V1–V4, 24 retailer-weeks) | Dropped pre-aggregation; those weeks peer-filled (D21) |
| Date 2022-02-28 duplicated in the pricing extract for 15 retailer-variant pairs | Day-mean first, then week-mean, so the day weighs once (D21) |
| Retailer carry windows differ (R1/R2/R3 start V1–V4 at 2022W04; R3 delists 2023W47; V5–V7 R4-only) | Price fill bounded to each pair's observed span; sole-carrier gaps carry own last price forward, `is_filled` ∈ {0,1,2} (D21) |
| V12 shows 1 unit of ST+SI at 2023W18, after its 2022W14 sell-out | Kept as-is; tests assert post-EOL activity ≤ 1 unit |
| V5–V7 have no stated release week yet first sell at 2022W43 | `release_week NULL` = "not stated"; selling windows must be derived from actuals |
| Fiscal-2024 Promo Q4 seasonality rows internally inconsistent | Stored as given with `is_consistent=0` flag; excluded from strict calendar test; client question (D22) |
| Pricing dates map to weeks as Fri–Thu (through 2022W22) then Thu–Wed — not Mon–Sun | `calendar.approx_monday` is display-only; nothing joins daily dates onto weeks via it |

### Calendar subtleties (verified in Phase 1)

- **Fiscal 2021 has 53 weeks and a 14-week Q1** (quarter boundaries 2021: W14/W27/W40/W53; other years: W13/W26/W39/W52). Ground truth: the seasonality sheet maps 2021 XMAS to `2021_Q1_14` ↔ `2021_14` while 2022+ map XMAS to Q1 week 13. Consequence: the dataset starts exactly at a quarter boundary (2021W41 = 2021Q4W1) and actuals end exactly at one (2023W39 = 2023Q3W13).
- **Pricing extends into the forecast window** (through fiscal 2024W27; calendar dates to 2024-03-29) — future promo prices are known-ahead features for the forecast layer.
- Approximate calendar dates anchor on fiscal 2021W43 ⊇ 2021-07-20 (pricing launch), weeks Mon–Sun; display-only.

## 7. Glossary

**WOS** weeks of supply (run-out basis here, see D11) · **MPS** master production schedule · **Pack-out** finishing/packaging a variant for shipment (slot-limited) · **Sell-Through (ST)** end-customer sales · **Sell-In (SI)** shipments from us to retailer · **NPI** new product introduction · **EOL** end of life · **CQ** current quarter (fiscal Q ending 2023W39) · **Kanban** near-line buffer stock · **CTB** clear-to-build.
