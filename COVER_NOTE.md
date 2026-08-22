# Cover note

**How I spent the time.** Roughly: a quarter on data forensics and ingestion —
the workbook's week labels turn out to be a fiscal calendar (October start,
53-week 2021 with a 14-week Q1), which every later layer depends on getting
right. A quarter on the forecast: global XGBoost quantile models on a log
scale, backtested on 13 hidden weeks against honest baselines, with analog
launch ramps for the two zero-history exclusives. A quarter on the MILP
(capacity, pack-out slots, two-tier WOS inventory, freight frontier) plus an
independent validator layer that re-checks every hard constraint after every
solve. The rest on the scenario, the Next.js UI, tests, and the deck.

**What I'd build with another week.** Rolling-origin backtesting (three folds
instead of one); per-geo volume caps inside the MILP rather than variant-level;
a scenario editor in the UI (arbitrary caps, re-solve from the browser); a
Chronos/TimesFM head-to-head on the same holdout harness; and a cost curve for
the WOS-target-vs-air-freight dial, which is the most consequential policy
choice in the plan.

**Look at first.** `deck/slides.html` for the story; `python engine/verify.py`
for a 10-second independent audit of every headline number; `docs/decisions.md`
for all 25 decisions with the options that were on the table. The commit
history is per-phase and includes what two adversarial review rounds caught
(mutation-tested test gaps, a phantom-shipment exploit, a missing freight
mode) — I'd rather show the misses and fixes than pretend there were none.
