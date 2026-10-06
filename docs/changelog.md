# Changelog

All notable changes, newest first.

## 2026-10-07 — docs: sources, funding, user profile (`docs/funding-and-sources`)
- Spec v0.3: programmes can have several `program_sources` (programme/admissions/scholarship/fees pages, …); snapshots link to a source; extraction runs over all of a programme's sources together and every `source_quote` is traceable to its URL.
- Extraction never filters: it records every deadline and funding option faithfully, in whatever language the page uses. `deadlines` gain `funding_route` and `eligible_levels`; new `funding_options: list[Evidence[FundingOption]]` (type, covers, amount/currency, own deadline, eligibility; "not yet published" → `None`, LOW confidence).
- New §6.1: user profile (applicant type, degree level, funding priority) as plain SQLite state, never AI memory; a primary-deadline picker (plain code) applies it at display/planning time, with non-matching rounds shown as fallbacks.
- Programme page gains a Funding section; tracker cards gain a funding badge (Fully funded / Partial / Self-funded / Unknown — not yet published).
- `docs/programs.md` added: first 4 golden-set programmes (KAUST MS CS, EDISS Erasmus Mundus, KFUPM MS Data Science & Analytics, KSU MSc AI) with sources, roles and known tricky cases; resolves the golden-set open question.
- `CLAUDE.md`: added the "extraction records everything, profile chooses" principle.
- No code changes.

## 2026-10-06 — v1 step 1: foundation (`feat/foundation`)
- uv project (Python 3.12, src layout), ruff, pytest, Makefile (`dev`, `test`, `test-live`, `eval` placeholder, `lint`).
- `core/llm/`: the only Anthropic SDK call site. Own retry layer (429/408/409/5xx/connection errors, honours `retry-after-ms`/`retry-after`, exponential backoff with jitter; SDK `max_retries=0`, explicit 120 s timeout). Price table for Opus 5.5 / Sonnet 5.5 / Haiku 4.5; unknown models raise. Per-job cost guard (`VERIGRAD_MAX_COST_PER_JOB`). Every call logged to `llm_calls` with actual and estimated cost, tokens, latency, request ID, job and programme.
- Extraction schema (spec §4.1) with `ProposedEvidence` (Claude) / `Evidence` (+ code-set confidence).
- SQLModel tables (spec §4.2); `llm_calls` gains `job_id`, `program_id`, `estimated_cost_usd` and cache-token columns.
- Settings from `.env` via pydantic-settings; app starts without an API key. `VERIGRAD_MAX_COST_PER_PROGRAM` renamed to `VERIGRAD_MAX_COST_PER_JOB`; added `VERIGRAD_LLM_TIMEOUT_SECONDS`.
- FastAPI + Jinja2 + HTMX + Tailwind (CDN) skeleton: nav (Add, Tracker, Review, Plan, Dashboard, Costs), placeholder pages, no-key banner.
- 60 unit tests (cost maths, guard, retries, client logging, schema, web); optional live smoke test.
- Spec §4.2 / §9 updated for the job-scoped budget.

## 2026-10-06
- Project named **Verigrad**; repository created.
- Added `CLAUDE.md`, `.env.example`, README and starter docs.

## 2026-10-05
- Spec v0.2: web app replaces the CLI; user-facing modules; fetching policy; clearer prompt-injection defence.
- Spec v0.1: initial plan — extraction with source quotes and code-verified confidence, evals, tracker, planner.
