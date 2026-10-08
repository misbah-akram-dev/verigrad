# Changelog

All notable changes, newest first.

## 2026-10-08 — CI: GitHub Actions (`chore/ci`)
- `.github/workflows/ci.yml`: on every pull request and push to `main`; ubuntu-latest, Python 3.12 via `uv` (cached), `uv sync --locked`, `ruff check` + `ruff format --check`, then `uv run pytest`.
- CI installs Playwright Chromium (`--with-deps`) so the 21 browser tests run against the local fixture site rather than skipping.
- New test switch `VERIGRAD_REQUIRE_BROWSER=1` (set in CI): the `chromium` fixture fails instead of skipping when no browser launches, so a broken browser install can't pass silently. Local runs are unchanged.
- No secrets in CI: `live` tests stay excluded by the pytest `addopts`.
- README: CI status badge.
- No app code changes.

## 2026-10-07 — v1 step 2: fetch, snapshots, Add page (`feat/fetch`)
- Dependencies: `playwright`, `selectolax`, `python-multipart`. One-time browser install: `uv run playwright install chromium`.
- `program_sources` table (role-tagged URLs per programme); snapshots link to a source and gain `outcome_reason`, `url`, `final_url`, `http_status`, `snapshot_dir`, `visible_text_path`, `meta_path`, `reused_from_snapshot_id`.
- `core/fetch/`: Playwright snapshot of one source → `page.html`, `text.txt`, `visible_text.txt`, full screenshot, same-site JSON and PDFs (capped), `meta.json`. Settle wait, cookie-banner dismissal, `<details>` + `aria-expanded` toggle expansion with a navigation guard. robots.txt (RFC 9309), per-domain delay, outcome rules (SUCCESS / BLOCKED / FAILED / MANUAL_IMPORT). Evidence kept for blocked and failed attempts.
- Fetch once, reuse: a URL with a SUCCESS or MANUAL_IMPORT snapshot is reused by any programme (no new request); a per-source **Re-fetch** takes a new snapshot and keeps history.
- Manual import of a saved HTML page or PDF for blocked/failed sources; HTML rendered offline (JS off, network blocked) for visible text + screenshot.
- `core/jobs/`: background job runner on one worker thread with its own event loop (Proactor on Windows); job progress per source in `jobs.progress`; interrupted jobs marked failed on startup.
- Web: **Add** page (name + URLs with roles, "+ Add another URL" via HTMX), job page with a panel that polls every second, screenshot thumbnail, file links, Re-fetch and upload. Snapshot files served only from their folder; saved HTML served as `text/plain` with a sandbox CSP.
- Optional `VERIGRAD_BROWSER_CHANNEL` (`msedge`/`chrome`) to use an installed browser when the Chromium download is blocked.
- Tests: 144, of which 21 drive a real browser against a local fixture site on 127.0.0.1 (marked `browser`, part of `make test`, skipped with an install hint if no browser). First real run: 8/8 sources saved (fetch success rate 100%).

## 2026-10-07 — docs: eligibility restrictions + golden-set fix (`docs/funding-and-sources`)
- Added the missing `eligibility_restrictions: list[Evidence[Restriction]]` field (type nationality/gender/religious/other + condition; unstated → `"unknown"`, never assumed absent) to spec §4.1.
- §6.1: the primary-deadline picker now flags a programme **"not eligible"** when a stated restriction excludes the profile; surfaced on the programme page and tracker card (spec §1.4).
- `docs/programs.md`: moved KSU MSc AI out of the applying-programmes table into a new **Rejected** section alongside a generic gender-restricted example, as examples of exclusionary restrictions — it should never have been listed as a programme being applied to. Golden-set count corrected to 3 initial programmes (not 4); updated cross-references in spec §11 and `docs/project-status.md`.
- `CLAUDE.md`: corrected the Core principles line to "every deadline/funding option/**restriction**".
- No code changes.

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
