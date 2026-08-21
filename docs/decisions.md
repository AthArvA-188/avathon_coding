# Decision Log — Program Z Planner

Format: each decision lists the options considered, the choice, and why. Status **User** = chosen by the project owner; **Default** = chosen by the implementer, overridable — flag it and it will be revisited.

---

## D1. Core stack — Status: User
- **Options:** (a) Python-only (Streamlit/Dash); (b) XGBoost + Next.js + SQLite; (c) JS-only stack.
- **Choice:** **XGBoost** (forecasting), **Next.js** (UI), **SQLite** (storage).
- **Why:** Owner's call. XGBoost handles sparse/holiday-heavy tabular series well and supports quantile loss; SQLite satisfies the brief explicitly; Next.js gives a real planner UI.

## D2. Architecture — Status: User
- **Options:** (a) Python pipeline writes SQLite, Next.js reads it directly; (b) FastAPI service + Next.js frontend; (c) Next.js-only.
- **Choice:** **(a)** — batch pipeline → `planz.db` → Next.js API routes via `better-sqlite3`.
- **Why:** Fewest moving parts for a reviewer (two commands). The scenario toggle needs no live solver because baseline and scenario are both precomputed. "Re-run as inputs evolve" = re-run the pipeline command.

## D3. MPS solver — Status: User
- **Options:** (a) MILP via PuLP + CBC; (b) OR-Tools CP-SAT; (c) constructive heuristic.
- **Choice:** **(a) PuLP + CBC MILP.**
- **Why:** The ≤4-variants-per-week pack-out rule is binary — natural for MILP. CBC is free and pip-installable. Hard constraints stay hard; WOS deviations and freight cost form the objective, giving a defensible trade-off story. An independent post-solve validator re-checks every constraint (never trust solver status alone).

## D4. Forecast uncertainty — Status: User
- **Options:** (a) XGBoost quantile models P10/P50/P90; (b) residual-based intervals; (c) high/base/low demand scenarios.
- **Choice:** **(a)** — three quantile-loss models per the shared feature set.
- **Why:** Native to the chosen stack; per-series, per-week intervals the UI can shade; pinball loss on holdout gives a proper score for the intervals themselves.

## D5. Repository — Status: User
- **Options:** (a) private repo via gh CLI; (b) public via gh CLI; (c) owner creates repo manually.
- **Choice:** **(c)** — remote: `https://github.com/AthArvA-188/avathon_coding.git`. `program_z.xlsx` is committed so the repo is runnable stand-alone.
- **Why:** Owner's call; no gh CLI on this machine.

## D6. Python environment — Status: User (updated 2026-08-21)
- **Options:** (a) Python 3.13 system + `venv`; (b) dedicated conda env; (c) install `uv`.
- **Choice:** **(b)** — conda env **`avathon`** (Python 3.12), clean install from `engine/requirements.txt`. Owner requested conda explicitly.
- **Why:** Reproducible, isolated from system Pythons; miniconda already present. Resolved versions on this machine: numpy 2.5, pandas 3.0, xgboost 3.4, pulp 3.3.

## D7. Forecast grain — Status: Default
- **Options:** (a) model at SKU × Geo × Channel (customers pre-aggregated); (b) model at customer level, aggregate up.
- **Choice:** **(a)**, keeping the customer dimension in the DB for exploration and for the exclusives' retailer context.
- **Why:** (a) is the required output grain, reduces sparsity (154 raw series, many near-zero), and the customer split under G1 is stable. Exclusives are single-retailer anyway, so no information is lost for them.

## D8. Negative actuals (returns/adjustments, 218 cells) — Status: Default
- **Options:** (a) keep as-is everywhere; (b) clip to 0 everywhere; (c) keep in stored actuals, clip to 0 in the training target.
- **Choice:** **(c)**.
- **Why:** Stored actuals must stay faithful (net volumes, lifetime-cap accounting use them). But at weekly grain a negative demand target teaches the model nothing recoverable; clipping the target avoids chasing returns noise. Documented in the deck as an assumption.

## D9. Backtest design — Status: Default
- **Options:** (a) single 13-week holdout (2023W27–W39); (b) rolling-origin 3×13-week folds; (c) no holdout, in-sample only.
- **Choice:** **(a)** as the headline score, with the final model refit on all 104 weeks for the production forecast. Baselines: seasonal-naive (lag-52) and naive (lag-1). Metrics: WAPE, sMAPE, bias, pinball@P10/P90.
- **Why:** 13 weeks = one fiscal quarter incl. no major holiday cluster; honest yet simple. Rolling-origin is the "if another week" upgrade.

## D10. Lifecycle handling — Status: Default
- **Options for NPI (V10/V11, released 2023W49 — zero history):** (a) analog launch curves from V8/V9 scaled by lifetime volume; (b) flat spread of lifetime volume; (c) exclude from forecast.
- **Choice:** **(a)** — normalize V8/V9 weekly launch trajectories (share of lifetime volume by week-since-release), average, scale to each new variant's lifetime cap per geo, damp toward the cap.
- **Also:** V12 (sold out 2022W14) forecast ≡ 0. All exclusives/one-time-deals enforce **cumulative actuals + forecast ≤ lifetime cap** (V5 38k, V6 50k, V7 22k, V8 13,832, V9 20,058, V10 57,407, V11 23,689 across geos); a cap breach fails the pipeline.
- **Why:** Only defensible signal for zero-history SKUs is analog behavior + known lifetime volume; the brief flags cap-exceeding forecasts as invalid.

## D11. WOS definition — Status: Default
- **Options:** (a) run-out WOS (weeks of forward demand covered by current inventory, cumulative); (b) inventory ÷ avg demand of next 4 weeks; (c) ÷ avg of next 13 weeks.
- **Choice:** **(a) run-out WOS**, computed against the P50 forecast.
- **Why:** Demand is holiday-spiky; fixed-window averages misstate coverage in the weeks approaching the Black Friday/XMAS cluster — which is exactly when the scenario's supply gap propagates. Run-out answers the planner's actual question — "how many weeks until I stock out". Unit-tested; the deck notes sensitivity vs option (c).

## D12. Freight mode policy — Status: Default
- **Given table:** Air 1wk $7 (all geos); Ground 1wk $2.5 (G4); Fast Boat 5wk $3.5 (G1); Std Ocean 8wk $2 (G1); Std Ocean 11wk $2.5 (G2).
- **Assumptions for gaps:** G3/G5 have Air only; G4 uses Ground (dominates Air: same lead time, cheaper); no other modes exist. Raised as a client question.
- **Choice:** steady-state supply on the cheapest feasible mode per geo (G1 Std Ocean, G2 Std Ocean, G4 Ground, G3/G5 Air); the "Sea Freight 6 WOS" buffer applies to ocean-served geos; Air is the expedite lever, priced in the scenario diff.
- **Why:** Matches the Kanban+Sea structure in the Objective sheet; cost-minimal subject to lead-time feasibility; expedite-vs-stockout becomes an explicit, priced trade-off.

## D13. Scenario allocation rule (V2 vs V4) — Status: Default (finalize with data)
- **Options:** (a) proportional to forecast demand; (b) proportional to WOS shortfall (priority to the variant closer to stockout); (c) channel-commitment priority.
- **Choice:** **(b)** — each constrained week, allocate the 4,500 units to equalize projected run-out WOS across V2 and V4 (a "fill the lowest tank first" waterline rule), tie-broken by forecast demand. Implemented inside the MILP via the shared cap + WOS penalties, so the solver discovers the waterline; the rule is stated and verified post-hoc.
- **Why:** Proportional-to-demand ignores starting inventory (V2 and V4 enter the window with different cover); equalizing stockout risk minimizes the worst-case WOS breach, which is what the WOS-penalty objective encodes. Will be sanity-checked against (a) in the deck.

## D14. UI stack details — Status: Default
- **Choice:** Next.js (App Router) + TypeScript + Tailwind CSS + **Recharts** + **better-sqlite3** (read-only). Three views per PRD F5.
- **Alternatives:** Plotly (heavier), raw D3 (slower to build), Prisma (overkill for read-only).

## D15. Slide deck format — Status: User
- **Choice:** self-contained **HTML** slides in `deck/` (no external CDNs), print-to-PDF friendly. Owner asked for `.html` documents.

## D16. Testing — Status: Default
- **Choice:** pytest in `engine/tests/`: WOS calculator, constraint validators (weekly/quarterly caps, pack-out ≤4, V2+V4 cap), lifetime-cap enforcement, forecast scoring harness, fiscal-calendar mapping. UI gets a smoke test only.
- **Why:** Matches the brief's "tests where correctness matters most".

## D17. Data file in repo — Status: Default
- **Choice:** commit `program_z.xlsx` (450 KB) at repo root; treat as immutable (never written).
- **Why:** "Clone and run" beats "clone, then hunt for a file". Repo is private (owner's account) so client data is not published.

## D18. Sell-In derivation — Status: Default
- **Options:** (a) forecast Sell-In independently; (b) derive from Sell-Through + channel policy.
- **Choice:** **(b)** — Channels 1 & 2: SI ≡ ST (stated in Objective). Channel 3: SI = ST + Δ(reseller inventory) driving reseller stock toward 13 WOS.
- **Why:** Forecasting SI independently can contradict the SI=ST identity and double-count the reseller buffer; deriving it keeps the plan internally consistent and makes Channel 3 inventory drift a first-class scenario output.

## D20. Duplicate 'Region 2_' series (data quirk) — Status: Default
- **Found:** 4 Channel 3 / Geo G2 series (V1–V4) appear twice — once under regular `G2_000x` SKUs (~9k–29k units each) and once under a tiny `Region 2_` bucket (4–18 units lifetime) with blank PPN.
- **Options:** (a) merge into the main series; (b) keep as separate series, PPN derived from the variant number; (c) drop (loses 54 units).
- **Choice:** **(b)** — source fidelity; the series-unique key includes SKU; they aggregate away at the forecast grain anyway.

## D21. Price cleaning & fill policy — Status: Default (revised after adversarial review)
- **Found:** 168 daily rows (Retailer R2, V1–V4) with placeholder $0 prices; the date 2022-02-28 duplicated for 15 retailer-variant pairs; retailers have real carry windows (R1/R2/R3 start V1–V4 only at 2022W04, R3 delists at 2023W47, V5–V7 are R4-only).
- **Original v1 fill** (full 4-retailer × variant-week grid) fabricated 830 out-of-window prices — caught by the Phase 1 review workflow and replaced.
- **Choice:** (1) drop non-positive daily prices; (2) average per **day** first, then days into weeks (kills the duplicate-date double-weighting); (3) fill **only interior gaps within each retailer-variant pair's own observed span** — peer mean where a same-week peer exists (`is_filled=1`, 74 rows, incl. all 24 R2 zero-weeks), otherwise carry the pair's own last price forward (`is_filled=2`, 53 rows, sole-carrier V5–V7 gaps). Result: 2,199 truthful weekly rows, no invented retailer-variant pairs.
- **Why:** the Objective's "missing price in a week" rule presumes the retailer carries the product that week; extrapolating beyond carry windows would feed the forecast a fictional 4-retailer price landscape and mask R3's exit.

## D22. Fiscal-2024 Promo Q4 seasonality rows — Status: Default (client question)
- **Found:** the sheet's two fiscal-2024 Promo Q4 rows are internally inconsistent (`2024_Q4_02`↔`2024_42` implies Q4 starts W41; `2024_Q4_03`↔`2024_44` implies W42; every other 2024 row implies the standard W40).
- **Choice:** treat fiscal 2024 as a standard 52-week year; store the rows as given (they lie beyond both the data range and the horizon); exclude the two rows from the strict calendar test; raise with the client.

## D19. Horizon & calendar interpretation — Status: Default
- **Choice:** Actuals end **2023W39** (per the file, 104 filled weeks — the brief's "2023W26" text is stale). Horizon = **2023W40 → 2024W39** (52 weeks = 4 fiscal quarters of 13). Week labels are **fiscal** (FY starts ~calendar October; evidence: Black Friday = fiscal W09, XMAS = fiscal W13–14, pricing date 2021-07-20 ↔ fiscal 2021W43). CQ = fiscal quarter ending 2023W39, so the shortage window is **2023W40–2023W45**.
- **Verified in Phase 1:** fiscal 2021 is a 53-week year with a **14-week Q1** (quarter boundaries W14/W27/W40/W53; all other years W13/W26/W39/W52) — proven against the seasonality sheet's `CY_Qtr_Wk` column and unit-tested. The dataset starts and ends exactly on quarter boundaries.
- **Why:** Follow the data over the prose; the fiscal reading makes every holiday land where retail reality puts it.
