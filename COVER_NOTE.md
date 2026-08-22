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

**What I'd build with another week.** A Chronos/TimesFM head-to-head on the
same holdout harness (the one §3.4 thread left as a stance); live re-solve
from the browser so an approved what-if re-plans in-app instead of via the
CLI; rolling-origin backtesting; a Channel-3 reseller-drift curve in the
scenario view; and a cost curve for the WOS-target-vs-air-freight dial, the
most consequential policy choice in the plan.

**Look at first.** `deck/slides.html` for the story; `python engine/verify.py`
for a 10-second independent audit of every headline number; `docs/decisions.md`
for all 31 decisions and the options considered. The commit history is
per-phase and includes what five adversarial review rounds caught (a
phantom-shipment exploit, a prompt-injection path, a CSRF hole in the write
surface) — I'd rather show the misses and fixes than pretend there were none.
