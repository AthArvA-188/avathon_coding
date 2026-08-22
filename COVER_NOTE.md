# Cover note

**How I spent the time.** Roughly: a quarter on data forensics and ingestion —
the workbook's week labels are a fiscal calendar (October start, 53-week 2021
with a 14-week Q1) that every later layer depends on. A quarter on the
forecast: global XGBoost quantile models on a log scale, backtested on 13
hidden weeks against honest baselines, with analog launch ramps for the two
zero-history exclusives. A quarter on the MILP (capacity, pack-out slots,
two-tier WOS inventory, freight frontier) plus an independent validator layer
that re-checks every hard constraint after every solve. The rest on the
scenario, the Next.js UI, tests, the deck — and then three of the four §3.4
threads as working prototypes: LLM-augmented signals (text *and* images, with
a human approval gate and an eval harness), an agentic planning loop
(propose → verify → publish, verifier genuinely rejecting), and a
conversational planner (voice or text → intent → whitelisted SQL). Foundation
forecasting models are argued in the deck, not yet prototyped.

**What I'd build with another week.** The fourth §3.4 thread, made
measurable: a foundation-model head-to-head — Chronos, TimesFM and an
LLM-forecaster beside the shipped XGBoost — on the *same* 13-week holdout
harness, landing in **one results table** (WAPE, bias, pinball@P10/P90, per
segment and horizon) so "which model is better" becomes a measured verdict,
not a stance. The same treatment for the agentic side: more specialist
agents than today's forecast/signal/planner/verifier roles — demand-sensing,
inventory-rebalancing, freight-cost negotiation — each with pluggable LLM
backends, every configuration run through the identical validators and eval
harness into the same scoreboard, so the multi-agent design is chosen on
evidence the way prompt v3 beat v2. Then the operational list: live re-solve
from the browser so an approved what-if re-plans in-app instead of via the
CLI; rolling-origin backtesting; a Channel-3 reseller-drift curve in the
scenario view; and a cost curve for the WOS-target-vs-air-freight dial, the
most consequential policy choice in the plan.

**A note on the API key.** Everything runs offline, but the §3.4 prototypes
are Claude-backed when `ANTHROPIC_API_KEY` is set: claude-sonnet-5 extracts
the signals, reads the image notices, and parses planner questions. Without
it, deterministic stand-ins take the same slots and label themselves — and
image signals are skipped rather than guessed at.

**Look at first.** `deck/slides.html` for the story; `python engine/verify.py`
for a 10-second independent audit of every headline number; `docs/decisions.md`
for all 33 decisions and the options considered. The commit history is
per-phase and includes what five adversarial review rounds caught (a
phantom-shipment exploit, a prompt-injection path, a CSRF hole in the write
surface) — I'd rather show the misses and fixes than pretend there were none.
