# Changelog

All notable changes, newest first.

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
