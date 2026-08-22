# Cover note

**How I spent the time.** Roughly a quarter each on: data forensics and a
clean ingestion layer (xlsx → SQLite, immutable input, every stage atomic and
independently re-runnable); a quantile forecast (global XGBoost P10/P50/P90,
lifecycle-aware, backtested on 13 hidden weeks against honest baselines);
constraint planning (a MILP plus a transparent greedy heuristic, both
re-checked by independent validators after every solve); and the rest on the
shortage scenario, the Next.js UI, tests, the deck — and working prototypes
for three of the four §3.4 threads.

**Built — the highlights.**

- Forecast beats seasonal-naive by 13 WAPE points on the holdout; every
  headline number auditable in 10 seconds (`python engine/verify.py`).
- Two planning methods, one measured verdict: the MILP buys ~99k protected
  sales for ~$0.6M extra freight over the greedy plan.
- P10/P50/P90 plans side by side — at P90 no feasible plan meets demand:
  capacity binds, not the method.
- Shortage scenario with an in-app diff: a 6-week component shortage leaves
  an ~8-month supply scar.
- LLM signals from text *and* images (drag-and-drop upload), with provenance,
  versioned prompts, an eval harness that rejected a weak prompt, and a human
  gate that explains every refusal.
- Agentic loop — propose → verify → publish — whose verifier genuinely
  rejects (its first run caught a real integration bug).
- Conversational planner: voice or text → typed intent → whitelisted SQL; the
  LLM never generates numbers.
- Six adversarial red-team rounds; the misses and fixes are in the commit
  history, not hidden.

**With another week.** Foundation-model and multi-agent head-to-heads scored
into one results table on the same holdout/validator harness — "which option
is better" as a measurement, not an opinion; then live in-app re-solve and
rolling-origin backtesting.

**Look at first.** `deck/slides.html`; `python engine/verify.py`;
`docs/decisions.md` — 33 decisions with the options considered.
