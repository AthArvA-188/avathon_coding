# Technical Documentation — Program Z Planner

Living document: data dictionary, architecture, module map, DB schema. Updated as each phase lands.

## 1. Input data — `program_z.xlsx` (immutable)

Five sheets. All week labels in the workbook are **fiscal weeks**, not ISO calendar weeks.

### 1.1 Fiscal calendar

- Fiscal year runs ≈ **October → September** (e.g. fiscal 2022 ≈ Oct 2021 – Sep 2022).
- Evidence: pricing date 2021-07-20 maps to `YEAR_WEEK` 202143; Black Friday sits at fiscal week ~09 (late Nov); XMAS at fiscal week 13–14 (late Dec); Mother's Day at fiscal Q3 week 6 (May).
- Quarters are 13 weeks: Q1 = W01–W13 (the holiday quarter: Black Friday, XMAS), Q2 = W14–W26, Q3 = W27–W39, Q4 = W40–W52. Column labels roll `2021W41 … 2021W52, 2022W01 …`, i.e. the label year increments at W01. The precise label↔quarter mapping is materialized in the `calendar` table by the ingest step and unit-tested against the Strong Seasonality Weeks sheet (which provides `CY_Qtr_Wk` ground truth like `2023_Q1_09`).

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
- **MPS mechanics:** decision vars = production per variant-week (int), pack-out binaries, shipments per geo-mode; constraints = caps, ≤4 slots, inventory balance, lifetime caps, non-negativity; objective = WOS-deviation penalties + freight cost + smoothing term.
- **Scenario:** identical model + `prod[V2,w] + prod[V4,w] ≤ 4500` for w ∈ 2023W40–W45; allocation emerges from WOS-equalizing objective (D13) and is reported explicitly.

## 6. How to run

Placeholder — filled in Phase 1/6 (`start.ps1`/`start.sh`, pipeline CLI, `npm run dev`).

## 7. Glossary

**WOS** weeks of supply (run-out basis here, see D11) · **MPS** master production schedule · **Pack-out** finishing/packaging a variant for shipment (slot-limited) · **Sell-Through (ST)** end-customer sales · **Sell-In (SI)** shipments from us to retailer · **NPI** new product introduction · **EOL** end of life · **CQ** current quarter (fiscal Q ending 2023W39) · **Kanban** near-line buffer stock · **CTB** clear-to-build.
