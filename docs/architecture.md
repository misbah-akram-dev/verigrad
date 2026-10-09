# Architecture

> Living document. Update after any change to modules or data flow. Full detail: `spec.md` §3–§5.

## Data flow (v1)

```text
URL ─► fetch ─► snapshot ─► extract (Claude) ─► verify (code) ─► store ─► web pages
       Playwright  HTML,       fields +            checks 1–4 →     SQLite    Programme,
                   screenshot, source quotes       HIGH/MED/LOW               Review, Tracker,
                   JSON, PDFs                                                 Plan, Dashboard
                                         │
                 evals ── run extract + verify on golden snapshots → accuracy, calibration, cost
                 llm ──── wraps every Claude call: retries + cost/latency logging + per-job budget
```

## LLM call path (`core/llm/`)

```text
LLMClient.complete(purpose, messages, job_id?, program_id?, expected_output_tokens)
  1. model must be in pricing.MODEL_PRICES          → else UnknownModelError (no $0 rows)
  2. estimate = chars/4 input × in-price + expected_output_tokens × out-price
  3. if job_id: guard.check_budget(job_spend(job_id), estimate, MAX_COST_PER_JOB)
                                                     → else BudgetExceededError, no call made
  4. retry.call_with_retry(sdk.messages.create)      429/408/409/5xx/connection → backoff,
                                                     honours retry-after-ms / retry-after
  5. pricing.compute_cost(usage) → llm_calls row (cost_usd, estimated_cost_usd, tokens,
     latency_ms, request_id, job_id, program_id)
  6. LLMResult(over_budget = job spend now > budget)
```

## Fetch path (`core/fetch/`, `core/jobs/`)

```text
Add page ─► actions.add_programme ─► programs + program_sources + jobs row
                                   └► JobRunner.submit (1 worker thread, own event loop;
                                       Proactor on Windows — never FastAPI's loop)
service.run_fetch_job (per source, one browser per job):
  1. URL already has a SUCCESS/MANUAL_IMPORT snapshot? → reuse row (same folder), no request
  2. Politeness: robots.txt (RFC 9309, cached per origin) → per-domain delay (shared throttle)
  3. snapshot.snapshot_source: goto → prepare (settle, cookies, <details>/aria toggles,
     navigation guard) → page.html, text.txt, visible_text.txt, screenshot, json/, pdfs/
  4. blocking.classify → SUCCESS / BLOCKED / FAILED (+ reason) → meta.json + snapshots row
  5. jobs.progress (per-source state) ◄── panel polls /add/jobs/{id}/panel every 1 s
Blocked/failed source ─► upload ─► manual_import (offline render) ─► MANUAL_IMPORT snapshot
```

## Modules (`src/verigrad/`)
| Module | Responsibility | Status |
|---|---|---|
| `config.py` | Typed settings from `.env` (pydantic-settings); app runs without a key | Done (foundation) |
| `core/llm/` | Claude wrapper: `pricing`, `guard`, `retry`, `client`; logging to `llm_calls` | Done (foundation) |
| `core/store/` | SQLModel tables (spec §4.2) incl. `program_sources`, engine/`init_db`, repository (sources, snapshots, reuse, jobs, `fetch_stats`) | Done (steps 1–2) |
| `core/extract/` | `schema.py` (spec §4.1) done; prompts + extraction in step 4 | Schema done |
| `core/fetch/` | `text` (selectolax), `polite` (robots, per-domain throttle, site rule), `blocking` (outcome rules), `prepare` (settle, cookies, accordions), `snapshot` (Playwright capture), `service` (fetch job), `manual_import`, `actions` (what web routes call) | Done (step 2) |
| `core/verify/` | Checks 1–4 (v1), 5 (v2) → confidence | Not started |
| `core/jobs/` | `JobRunner` (worker thread + own event loop), per-source progress model | Done (step 2) |
| `core/tracker/` | `status` (lifecycle transitions, filters, drop reasons; pure), `service` (cards, actions, delete preview + delete), `files` (snapshot folder removal, only inside `data/snapshots/`) | Done (step 7, tracker part) |
| `core/plan/` | Backwards planning, timezones, `.ics` | Not started |
| `core/spider/` | (v2) Selector generation/repair, re-checks | Not started |
| `core/discover/` | (v2) Page discovery agent: one URL → on-site links (same parent domain, page/depth caps) → relevant pages → snapshots via `core/fetch/` (D31) | Not started |
| `evals/` | `python -m verigrad.evals` | Placeholder |

## Web (`src/verigrad/web/`)
`app.py` (factory + lifespan → `init_db`, `JobRunner`, interrupted jobs → failed), `routes.py` (home + placeholders), `fetch_routes.py` (Add, job panel, re-fetch, import, snapshot files), `tracker_routes.py` (Tracker page, status actions, delete confirm + delete), `templates/` (Jinja2 + Tailwind CDN + HTMX).
Pages: **Add** (built) · **Tracker** (built) · Programme · Review · Plan · Dashboard · Costs (placeholders until their step).

## Tracker path (`core/tracker/`)

```text
Tracker page ─► service.list_cards(filter) ─► programs + source counts + latest snapshot per source + latest job
card button ─► POST /tracker/programs/{id}/{action} (HTMX)
              ─► status.next_status (invalid → 409) ─► repo.set_program_status (+ status_changed_at)
              ◄── card partial + filter tabs (hx-swap-oob)
Delete (DROPPED only) ─► GET …/delete: footprint (rows, folders to remove, shared folders, cost rows)
                      ─► POST …/delete: repo.delete_program_rows (one transaction: promote reusers,
                         clear llm_calls ids, delete rows) ─► files.remove_snapshot_folders (unused only)
```

## Key decisions
| Date | Decision | Why |
|---|---|---|
| 2026-10-05 | Web app (FastAPI + HTMX), no CLI except `make eval` | Better demo; evals still need a command for CI |
| 2026-10-05 | Extraction runs on saved snapshots only | Repeatable evals, offline debugging, base for v2 spider |
| 2026-10-05 | Confidence set by code checks, not the model | Verifiable; calibration is measurable |
| 2026-10-05 | No proxies; blocked pages → manual upload | Tiny volume; polite fetching |
| 2026-10-06 | Cost budget is **per job**: `llm_calls.job_id` (guard sums by it) + `program_id` (Costs page) + `estimated_cost_usd` | A per-programme lifetime budget would be used up by repeated evals/re-extractions; logging the estimate lets us measure guard accuracy |
| 2026-10-06 | Our own retry layer; SDK built with `max_retries=0` and explicit timeout (`VERIGRAD_LLM_TIMEOUT_SECONDS`, 120 s) | One testable retry layer; retry by status code (SDK 1.x `OverloadedError` 529 is not an `InternalServerError`) |
| 2026-10-06 | Unknown model → `UnknownModelError` | Never record a call as $0 |
| 2026-10-06 | `ProposedEvidence[T]` (Claude output, no confidence) vs `Evidence[T]` (+ confidence, failed_checks) | Enforces "Claude proposes, code verifies" in the type system |
| 2026-10-06 | Models: extract `claude-sonnet-5-5`, compare `claude-haiku-4-5`; price table Opus 5.5 / Sonnet 5.5 / Haiku 4.5 | Revisit after first eval run |
| 2026-10-06 | `SQLModel.metadata.create_all`, no migrations tool | Local single-user DB; revisit if schema churn hurts |
| 2026-10-07 | Programmes can have several `program_sources` (program/admissions/scholarship/fees); snapshots link to a source, extraction runs over all of a programme's sources together | Deadlines and funding often live on separate pages from the main programme page (spec §4.2, `docs/programs.md`) |
| 2026-10-07 | Extraction records every deadline/funding option with no filtering; `deadlines` gain `funding_route`/`eligible_levels`, new `funding_options: list[Evidence[FundingOption]]` | Filtering during extraction would silently drop real options; the user profile picks later (spec §4.1, §6.1) |
| 2026-10-07 | User profile (applicant type, degree level, funding priority) is plain SQLite state; a primary-deadline picker (plain code) applies it, other rounds shown as fallback | Keeps profile-driven picking out of AI memory and testable like the rest of planning (spec §6.1) |
| 2026-10-07 | Fetch jobs run on one worker thread with their own `asyncio.Runner` (ProactorEventLoop on Windows) | uvicorn `--reload` uses a SelectorEventLoop on Windows, which can't start Playwright; one worker also serialises fetches (`docs/decisions.md` D21) |
| 2026-10-07 | Fetch once per URL; shared admissions/scholarship URLs reuse the existing snapshot; Re-fetch is explicit | Polite fetching (D8); several programmes share central pages (D22) |
| 2026-10-07 | robots.txt per RFC 9309; disallow → BLOCKED (upload offered); network failure → page fetch reports the real error | Polite, and never asks for an upload of a mistyped URL (D23) |
| 2026-10-07 | JSON and PDFs captured from the same parent domain only; skipped links listed in `meta.json` | Skips analytics/third-party noise; visible record of what was left out (D24) |
| 2026-10-07 | Manual HTML imports rendered offline (JS off, network blocked); snapshot HTML served as `text/plain` + sandbox CSP | Keeps visible-text/hidden-text check working for uploads; untrusted HTML never renders on our origin (D25, D26) |
| 2026-10-07 | Optional `VERIGRAD_BROWSER_CHANNEL` (msedge/chrome); default bundled Chromium | Fallback when the Chromium download is blocked (D27) |
| 2026-10-07 | New `eligibility_restrictions: list[Evidence[Restriction]]` (nationality/gender/religious/other); unstated → `"unknown"`, never assumed absent; the picker flags a programme "not eligible" when a restriction excludes my profile | Real programmes exist with nationality- or gender-based restrictions that exclude the user outright; must surface this instead of silently tracking an inapplicable programme (spec §4.1, §6.1, `docs/programs.md`) |
| 2026-10-09 | Status lifecycle = spec §6 + undo result + withdraw; restore → TARGETING; Applied filter includes results | Mis-recorded results must be fixable; withdrawing is a real step (D29) |
| 2026-10-09 | Permanent delete only for DROPPED; reused snapshot handed to the oldest reusing row; `llm_calls` kept with ids cleared; folders removed only when unused | Safe two-step delete that keeps shared pages, the fetch success rate and total spend correct (D28) |
| 2026-10-09 | The user tracks **offerings** (programme + degree level), not pages: extraction returns `offerings: list[Offering]`, each value with an applicability (degree levels or "not stated"); tables decided in step 3 | One page covers several degree levels and one offering's facts span several pages (D30) |
| 2026-10-09 | v2 page discovery agent (`core/discover/`): its only tool fetches already-found, same-site links | One pasted URL should be enough; link-following stays on-site and can't be redirected by a page (D31) |
| 2026-10-08 | GitHub Actions CI (lint + full `pytest`, Chromium installed); `VERIGRAD_REQUIRE_BROWSER=1` turns browser-test skips into failures; no secrets, `live` excluded | Browser tests must actually run somewhere on every PR; no API key in CI |
