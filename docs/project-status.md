# Project status

> Read at the start of every session. Update at the end of every session.

**Current milestone:** v1 — Extraction engine + web app
**Target:** v1 demo by end of week 2 (may run into early week 3)
**Last session:** 2026-10-07 — docs-only: sources, funding, user profile decisions recorded in spec; `docs/programs.md` created (`docs/funding-and-sources`)

## v1 build steps (spec §2)
- [x] 1. Repo setup, LLM wrapper, extraction schema, SQLite store, FastAPI skeleton
- [ ] 2. Fetch + snapshots + Add page; snapshot ~30 real programme pages
- [ ] 3. Hand-label 5 programmes; fix schema
- [ ] 4. Extraction + Programme page
- [ ] 5. Verification checks 1–4 + confidence badges
- [ ] 6. Label remaining ~25; `make eval`; baseline; Dashboard page
- [ ] 7. Tracker + Review pages
- [ ] 8. Planner + Plan page + `.ics`

## Numbers so far
| Metric | Value | Date |
|---|---|---|
| Field accuracy | — | |
| Calibration (H/M/L) | — | |
| Cost per programme | — | |
| Cost estimate accuracy (`estimated_cost_usd` vs `cost_usd`) | — | |
| Fetch success rate | — | |
| Unit tests | 60 passing (no network) | 2026-10-06 |

## Open questions
- ~~Golden-set programme list~~ Resolved: initial 4 in `docs/programs.md` (KAUST MS CS, EDISS Erasmus Mundus, KFUPM MS Data Science & Analytics, KSU MSc AI); target ~30 by step 6. Next step is still step 2.
- ~~Scholarships: v1 or v2?~~ Resolved: v1, via `funding_options` (spec §4.1); see `docs/changelog.md` 2026-10-07.
- Default extraction model + comparison model: provisionally `claude-sonnet-5-5` / `claude-haiku-4-5`; decide after first eval
- Is the chars/4 + expected-output estimate good enough for the per-job guard? Measure once extraction runs.
- Default `expected_output_tokens` (4000) and `VERIGRAD_MAX_COST_PER_JOB` ($0.30): tune after first real runs

## Blockers / setup notes
- Local `.env`: rename `VERIGRAD_MAX_COST_PER_PROGRAM` → `VERIGRAD_MAX_COST_PER_JOB` (old name is ignored; default $0.30 applies). Optionally add `VERIGRAD_LLM_TIMEOUT_SECONDS=120`.
- Windows: `winget install ezwinports.make` for the Makefile.

## Where we left off
Step 1 done: uv project (Python 3.12), Makefile, `core/llm/` wrapper (retries honouring retry headers, per-job cost guard, `llm_calls` logging with estimated vs actual cost), extraction schema, SQLModel tables, settings, FastAPI skeleton with nav + placeholder pages. Merged via `feat/foundation`.
Docs-only update (`docs/funding-and-sources`): spec records multiple sources per programme (`program_sources`), extraction-never-filters rule, `funding_options` schema, and the user-profile + primary-deadline picker (spec §4.1, §4.2, §6.1, §7). `docs/programs.md` created with the first 4 golden-set programmes.
Next: step 2 — Playwright fetch + snapshot folder + `program_sources` + Add page with background job and progress; then snapshot ~30 real programme pages.
