# Program Z — Demand Planning Mini-Application

Take-home submission: 4-quarter demand forecast, MPS + pack-out plan, and V2+V4 enclosure-shortage scenario for a premium wearable, built as a runnable app.

**Stack:** Python 3.13 (XGBoost forecasting, PuLP/CBC MILP planning) → SQLite → Next.js UI.

> 🚧 Planning phase complete; implementation in progress. See [`docs/progress.md`](docs/progress.md) for live status.

## Documents

| Doc | Purpose |
| --- | --- |
| [`ASSIGNMENT.md`](ASSIGNMENT.md) | The brief, as received |
| [`docs/PRD.md`](docs/PRD.md) | Product requirements distilled from the brief |
| [`docs/decisions.md`](docs/decisions.md) | Every decision, the options considered, and why |
| [`docs/progress.md`](docs/progress.md) | Phase-by-phase progress log |
| [`docs/documentation.md`](docs/documentation.md) | Data dictionary, architecture, schema, modelling notes |

## Quick start

Placeholder — will become: one command to set up (`start.ps1` / `start.sh`), one to ingest + compute (`python engine/run_pipeline.py --all`), one to launch the UI (`npm run dev` in `app/`).

## Repository layout

See [`docs/documentation.md`](docs/documentation.md) §3. Input `program_z.xlsx` is treated as immutable — read, never written.
