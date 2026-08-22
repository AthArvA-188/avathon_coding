# Talking points — the ten decisions, as 30-second stories

Every story has the same five beats: **the problem → the options → what I
picked → the number that proves it → the pushback answer**. Rehearse the
beats, not the words. Full detail behind each: `docs/decisions.md` (D1–D30).

---

## 1. Why XGBoost and not Prophet/ARIMA per series?

**Problem:** 124 series, most too sparse to model alone; holiday weeks dominate.
**Options:** per-series classical models; one global ML model; foundation models.
**Picked:** one global XGBoost — sparse series borrow strength from rich ones,
and the promo calendar becomes an explicit feature instead of a hoped-for cycle.
**Number:** 37.6% holdout WAPE vs 50.7% for seasonal-naive — a 13-point win.
**Pushback ("37% is high"):** at SKU × geo × channel × *week* grain that's the
nature of the beast — which is exactly why we report against baselines. A model
that can't beat "same week last year" is worthless; ours beats it on every core
variant.

## 2. Why quantiles (P10/P50/P90) instead of one number?

**Problem:** planners buy safety stock against risk, not averages.
**Picked:** three quantile models; trained on log(units) because quantiles pass
through monotone transforms exactly — the math is clean, not approximate.
**Number:** the experiment log: raw target 53% WAPE → log 41% (bias −30%) →
+volume weights 37.6% with bias +3.3%. Each step scored on the same holdout.
**Pushback:** "why not intervals from residuals?" — quantile loss learns
asymmetric, per-week uncertainty (holiday weeks have wider bands); residual
bands are one-size-fits-all.

## 3. How can you forecast V10/V11 with zero history?

**Problem:** both launch inside the horizon; nothing to fit.
**Picked:** analog launch curves from the earlier exclusives (V8/V9),
deseasonalized, re-shaped to FY2024's holiday calendar, scaled to the committed
deal volumes.
**Number:** ramps sum to exactly 57,407 and 23,689 — the deal sizes.
**Pushback:** "that's a heuristic!" — yes, deliberately: with zero history the
defensible signal is analog behavior plus a known contract size. This is also
the first place I'd trial a foundation model (Chronos/TimesFM) — the harness to
score it already exists.

## 4. The "lifetime volume" contradiction

**Problem:** V8 had already sold 2.4× its stated "lifetime volume".
**Picked:** read exclusive volumes as *forward* volumes from today (the only
self-consistent reading); one-time-deal numbers behave as true lifetime totals
(V7 is at 20,983 of 22k and demand collapsed to ~4/week — the cap is visibly real).
**Pushback:** it's flagged as a client question, not buried — slide 16.

## 5. Why a fiscal calendar and how do you know?

**Problem:** "2021W41"-style labels don't say what a week *is*.
**Picked:** fiscal year starting ~October; fiscal 2021 has 53 weeks with a
14-week Q1.
**Number:** the workbook's own promo sheet maps XMAS to Q1-week-14 in 2021 but
Q1-week-13 every other year — that's the proof, and it's a unit test.
**Pushback:** get this wrong and every holiday lands a week off; it silently
poisons everything downstream. That's why it was decision #1 of the build.

## 6. Why a MILP — and can you defend it without hand-waving?

**Problem:** the ≤4-variants-per-week pack-out rule is a binary decision;
greedy choices interact across 52 weeks.
**Picked:** MILP (PuLP/CBC) — but I also built the alternative: a greedy
heuristic any planner could execute by hand. Same inputs, same validators.
**Number:** greedy is cheaper ($4.62M vs $5.22M freight) and holds fatter
buffers — and leaves **99,455 units unmet vs zero**. Lookahead is worth ~99k
protected sales for ~$0.6M of freight.
**Pushback ("optimizers are black boxes"):** that's why the heuristic exists,
why an independent validator re-checks all 9 rules after every solve, and why
a zero-production plan was *proven* (by mutation testing) to be catchable.

## 7. Why is the plan's WOS so far below the 12-week target?

**Problem:** median supply cover is ~1 week against a 12-week target.
**Answer:** that's a *finding*, not a bug: annual demand (953k) exceeds annual
capacity (896k). Something must give; the objective ranks unmet demand ≫
channel stock > supply buffer, so buffers are consumed to protect sales —
which is what a planner would choose, made explicit.
**Number:** three of four quarters at exactly 224,000; unmet demand 0.

## 8. Why does the plan fly $4.68M of air freight?

**Answer:** a unit produced just-in-time in a capped week physically cannot
make an ocean lead. The air bill ≈ the shadow price of capacity.
**Number caveat I volunteer first:** the air/ocean split flips on the supply-WOS
penalty weight (threshold ≈ $0.71/unit-week vs the chosen $2) — it's a policy
dial, and I say so on the slide. Volunteering the caveat is stronger than
having it found.

## 9. The shortage scenario — what did the allocation "rule" turn out to be?

**Picked:** don't hand-pick a split; let the WOS-equalizing objective allocate.
**Number:** it alternated full 4,500-unit weeks (slot economics) → exact 50/50;
volume lost only −346 units, but the supply position trails baseline until
**2024W29** — a 6-week shortage, an ~8-month scar, because there's no spare
capacity to catch up.
**Recommendation:** protect the *component* before the holiday build; the
finished-goods plan can't absorb it.

## 10. How do you know any of this is correct?

**Answer, in layers:** 73 tests (with double-entry expected values), 9
independent validators after every solve (incl. replaying all inventory math
from shipments), `verify.py` — a 14-check auditor sharing no code with the
pipeline — and two adversarial review rounds that mutation-tested the suite
and caught real gaps (fabricated price fills; a do-nothing plan passing
validation; a phantom-shipment exploit). The misses and fixes are in the
commit history on purpose.

---

### If you only rehearse three numbers

- **37.6% vs 50.7%** — the forecast earns its keep.
- **953k vs 896k** — the year is capacity-starved; everything follows from this.
- **99,455 vs 0** — why the optimizer beats the sensible-looking simple method.
