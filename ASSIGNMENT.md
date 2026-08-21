# Demand Planning Take-Home — Program Z

**Tech stack**: Your choice (see [Stack](#stack)).
**Deliverables**: A runnable mini-application, a slide deck, and source code (see [Deliverables](#deliverables)).

---

## 1. Context

You are joining a team that builds AI-assisted supply-chain planning systems. A consumer-electronics client ships a premium wearable product internally codenamed **Program Z** through global retail channels. They've handed us roughly two years of weekly sell-through, sell-in, and pricing data, plus a brief on their planning parameters (WOS targets, freight options, capacity caps, pack-out rules). They want to know:

1. **What does demand look like over the next 4 quarters, per SKU, per geography, per channel?**
2. **What Master Production Schedule (MPS) and weekly pack-out plan supports that demand while respecting capacity and pack-out rules?**
3. **What changes when a shared upstream component disrupts two variants simultaneously for the first 6 weeks of next quarter?**

And — because the team you'd be joining builds AI-assisted planning systems — they also want a point of view on **where this stack should go next**: foundation forecasting models, LLM-augmented signals, and agentic planning loops. See [§3.4](#34-next-generation-modelling--agentic-planning).

Your job is to deliver a defensible answer to all three and package it as a system someone on the planning team could actually run and re-run as inputs evolve.

This is **not** a notebook-and-PDF exercise. We want to see you build something that takes the xlsx in, runs the math, and presents the result.

---

## 2. The Data — `program_z.xlsx`

One Excel file, five sheets. Treat it as immutable input — read it, never overwrite it.

| Sheet | Shape | Purpose |
| --- | --- | --- |
| **Pricing Data** | 13,803 rows × 6 cols | Daily retail price observations for the top 4 Geo G1 retailers across 7 SKUs. |
| **Strong Seasonality Weeks** | 13 events × 4 years | Promo/holiday calendar (Promo Q1, Black Friday, Cyber Monday, XMAS, Mother's Day, Father's Day, Promo Q4, etc.). |
| **Variant Details** | 12 variants | SKU classification (Core / One Time Deal / Exclusive), release weeks, and exclusive lifetime volumes by geo. |
| **Data - 104 weeks** | 308 rows × 156 week cols | Weekly **Net Sell-Through** and **Sell-In (Billings)** by Channel × Geo × Customer × SKU. Actuals run **2021W41 → 2023W26** (91 filled weeks); cells from **2023W27 → 2024W39** are blank — that is the window you forecast into. |
| **Objective** | 30 rows | The planning brief: callouts, WOS targets, OEM location, freight options, capacity caps, MPS objective, and the shortage scenario. |

### Key dimensions

- **Channels**: Channel 1, Channel 2, Channel 3. *For Channels 1 and 2, Sell-In equals Sell-Through.* For Channel 3 there's a reseller buffer.
- **Geos**: Geo G1 (~90% of volume), Geo G2, Geo G3, Geo G4, Geo G5.
- **Customers** (under Geo G1): Retailer R1, Retailer R2, Retailer R3, Retailer R4, *Rest of Geo G1*. Outside G1, customers are aggregated as *Rest of World* or appear as the retailer (for exclusive variants).
- **SKUs**: 12 variants (V1–V12). V1–V4 are Core; V5–V7 are One Time Deals (Retailer R4); V8–V11 are retailer-exclusives; V12 is a discontinued drop.
- **Metrics**: `Net Sell-Through` (end-customer demand) and `Sell-In (Billings)` (volume shipped from us to the retailer).

### Things to notice before you model

- The data is sparse — many SKU × geo × customer × channel cells are zero by design (a Retailer R3-exclusive variant has no Retailer R4 rows).
- Some weeks contain **negative** values (returns / adjustments). Decide how to handle them.
- Exclusive variants have **lifetime volume caps** — see `Variant Details`. A forecast that exceeds the cap is invalid.
- Pricing data covers only the top 4 Geo G1 retailers, only 7 of the 12 SKUs, and starts at the launch date (2021-07-20). For weeks where a top retailer is missing a price, treat it as equal to a peer retailer's price that week (stated explicitly in the Objective sheet).
- The OEM is in **Thailand**. Lead times in the Objective sheet are *from OEM to the destination DC*.

---

## 3. What we want you to build

Three problems. They build on each other — do them in order.

### 3.1 Demand forecast (SKU × Geo × Channel × Week, 4-quarter horizon)

- **Target metric**: `Net Sell-Through` at the SKU × Geo × Channel × Week grain.
- **Horizon**: From the last actual week in `Data - 104 weeks` through 4 quarters forward.
- **Inputs you can use**: Historical sell-through, sell-in, pricing, the seasonality calendar, variant classification, and any external signal you can justify.
- We expect you to:
- Decide on a baseline (seasonal naive, ETS, Prophet, ML — your call) and document why.
- Explicitly model the holiday calendar — these weeks are anomalies and a naive forecast will underfit them.
- Account for variant lifecycle: NPI ramps (new variants from V8 onwards), EOL behavior (V12), and lifetime-volume caps for exclusives.
- Quantify forecast uncertainty in some form (intervals, scenarios, residual analysis — your call).
- Produce a forecast table the downstream planner can consume directly.

### 3.2 Master Production Schedule (MPS) + Pack-out plan

Given your forecast, build a weekly MPS over 4 quarters that:

- Targets the WOS levels stated in the Objective sheet (Kanban + Sea Freight = 12 WOS; Channel Inventory = 13 WOS).
- Respects the **weekly capacity cap (17,280 units)** and **quarterly capacity cap (224,000 units)**.
- Respects the pack-out rule: **only 4 variants can be packed out in any given week**.
- Chooses a freight mode mix (Air / Ground / Fast Boat / Standard Ocean) per Geo using the lead times and per-unit costs in the Objective sheet.

You decide whether to model this as LP/MILP, a constructive heuristic, or something else — but **the solution must respect every hard constraint** above, and you must be able to explain trade-offs (cost vs. coverage, WOS overshoot vs. stockout risk, etc.).

### 3.3 Constraint scenario — shared enclosure shortage (V2 + V4)

The Objective sheet states that **Variants V2 and V4 share an enclosure component** whose supplier has flagged reduced material availability for **the first 6 weeks of CQ+1** (where CQ = the quarter containing the last actual week of data). Combined supply across V2 and V4 is capped at **4,500 units/week** for those 6 weeks. After that, supply normalises.

This is a multi-SKU constraint, not a single-variant shortage. Your scenario must:

- **Re-run the MPS** under the shared cap.
- **Allocate scarce supply** across V2 and V4 each week of the constrained window — and *justify* the allocation rule (proportional to forecast demand? to WOS shortfall? to channel commitment priority? to something else?).
- **Surface the downstream impact**: which weeks lose pack-out slots, which Geos absorb the WOS hit first, how Channel 3 reseller inventory drifts, what the in-quarter recovery curve looks like once supply normalises.
- **Compare baseline plan vs. shortage plan side-by-side** — total volume delta, cost delta (incremental freight if expedited), WOS-target violations per Geo, and stockout-week count by SKU.

A planner should be able to toggle the scenario on/off in your app and see the diff.

---

### 3.4 Next-generation modelling & agentic planning

You're interviewing with a team that builds AI-assisted planning systems, so we want a point of view on how this problem evolves past a deterministic spreadsheet replacement. **At minimum, address each of the four threads below in your deck.** Prototyping any of them is optional but is the clearest way to differentiate a strong submission.

- **Foundation forecasting models.** Time-series foundation models — TimeGPT, Chronos, TimesFM, Moirai, Lag-Llama, etc. — are production-viable for many forecasting use cases. Where in *this* problem would you reach for one vs. a classical or task-specific ML baseline (think: sparse SKUs, short NPI history, holiday-heavy weeks, retailer-exclusive low-volume series)? What's the failure mode you'd watch for? If you prototype one, score it head-to-head against your baseline on the same holdout window.

- **LLM-augmented signals.** The provided data is structured numerics; in the real world a planner also reads unstructured signals (analyst notes, supplier emails, retailer feedback, competitor launches, news). Sketch how you'd let an LLM ingest and weight those signals into the forecast or the scenario layer — and what you'd do to keep it auditable (provenance, override logs, versioned prompts, eval harness).

- **Agentic planning loops.** Problems 3.1–3.3 read naturally as a multi-agent pipeline: a *forecasting agent*, a *planner agent* that proposes the MPS, a *verifier agent* that checks every hard constraint, a *scenario agent* that re-plans under disruption. Show how you'd decompose responsibilities, where each agent's authority ends, how they hand off, how they recover from a constraint-violation rejection, and where the human-in-the-loop intervenes. A diagram in the deck is fine.

- **Conversational planner UX.** What would a natural-language interface to your planner look like — *"what if Retailer R4 doubles their Q4 order on V3?"*, *"reschedule pack-out to keep V1 above 12 WOS in G1 even if V12 stocks out"*, *"explain why V8's plan changed this week"* — and which of those questions are answered deterministically vs. need an LLM? What guardrails prevent a generated plan from violating capacity caps or pack-out rules?

You do not need to build all four. You **do** need to convince us you've thought about where this stack is heading and how this specific problem maps onto it.

---

## 4. Deliverables

We are evaluating you on three artifacts. All three matter.

### 4.1 A runnable mini-application

Something a non-author can clone and run. Concretely:

- **One command to set up** (a `start.sh`, `make`, `docker compose up`, or equivalent).
- **One command to ingest** `program_z.xlsx` into whatever store you choose (sqlite is fine; Postgres is fine; pandas + parquet is fine).
- **A UI** that lets a planner:
- Inspect the forecast (filter by SKU / Geo / Channel / week).
- View the MPS + pack-out plan (week-by-week schedule, freight mode chosen per Geo, capacity utilization).
- Toggle the V2+V4 enclosure-shortage scenario and see the diff vs. baseline.
- The UI doesn't need to be pretty — but it must be functional and self-explanatory. Streamlit, React, Gradio, Dash, a static HTML report bound to a Python backend — anything that **renders an answer** and lets us interact with it counts.

For reference, an internal project of similar scope splits responsibilities as: data ingestion (xlsx → tabular store), a deterministic planning engine (forecast + MPS + pack-out + scenario), and a thin web UI on top. You're not required to match that architecture, but it's a reasonable target.

### 4.2 A slide deck (~12–16 slides)

Build it for a planning lead who has not seen your code. Include:

- The business framing (1–2 slides).
- Your modelling approach for the forecast — what you tried, what you kept, why (2–3 slides).
- The MPS + pack-out approach and the constraints that drove it (2–3 slides).
- Headline results: forecast quality on a holdout window, total planned volume, WOS achieved, capacity utilization, freight cost (2–3 slides).
- The V2+V4 enclosure-shortage scenario: the allocation rule, the diff vs. baseline, the cost, the recommendation (2 slides).
- **Next-gen modelling & agentic flows** — how this stack should evolve: foundation forecasting, LLM-augmented signals, agent decomposition, conversational planner UX (1–2 slides). See [§3.4](#34-next-generation-modelling--agentic-planning).
- Assumptions & open questions you'd raise with the client (1 slide).

PPTX, PDF, Keynote, or HTML — whatever you like.

### 4.3 The source code

- Git repository (zip is fine if you don't want it public).
- A `README.md` covering: prerequisites, setup, ingest, how to launch the app, where the key code lives, and any known limitations.
- Tests for the bits where correctness matters most (your forecast scoring harness, the capacity / pack-out constraint validation, the WOS calculation — at minimum).
- Brief commit history that lets us see how you worked. Squashing the entire build into one commit is a negative signal.

---

## 5. Stack

Pick what makes you productive. Reasonable choices:

- **Language**: Python
- **Forecasting**: Prophet, statsforecast, NeuralProphet, lightgbm, XGBoost, classical ETS/ARIMA, or your own — all fair.
- **Optimization**: PuLP, Pyomo, OR-Tools, Gurobi (community), a constructive heuristic, or a custom solver — all fair as long as the constraints hold.
- **UI**: React + FastAPI / Next.js — your call.
- **Storage**: SQLite is more than enough. Parquet on disk is fine. No need for a managed database.

**LLMs**: You may use Copilot, Claude Code, Cursor, ChatGPT, etc. We don't penalize that. Two rules:
1. *You* must be able to explain every line of code in your submission and every modelling decision in your deck.
2. Don't paste sample answers from public take-homes that resemble this one. We will spot it.

---

## 7. Submission

Send us:

- A link to the repository (GitHub / GitLab) **or** a zip containing the full repo.
- The slide deck (as a separate file, or linked from the README).
- A short cover note (≤300 words): how you spent your time, what you'd build next if you had another week, anything you want us to look at first.

Submit by replying to the original assignment thread. We confirm receipt within 1 business day and aim to give you a decision (with feedback) within 5 business days.

---

## 8. Questions

If something in the data or brief is ambiguous, **make a defensible assumption, document it in your deck, and move on** — we'd rather see judgment than a 3-day delay waiting for a clarification.
