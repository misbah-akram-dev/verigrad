# Changelog

All notable changes, newest first.

## 2026-10-10 — fetcher reveals collapsed and tab panels (`fix/reveal-panels`)
- Found on all 3 golden-set programmes: `visible_text.txt` missed real content. KFUPM's 47 programme panels were never opened (Bootstrap buttons say `collapsed` but `aria-expanded="true"`), only KAUST's active tab rendered (English Language and GRE/PGAT were missing), and EDISS's single-open accordion left 26 of 27 country sections closed.
- `prepare.reveal_panels`: after the existing expansion, a DOM-only pass (no clicks) shows hidden panels that a rendered toggle points at by id (`aria-controls`, `data-*target="#id"`, `href="#id"`). Tab toggles may sit in a `nav`; other toggles must be outside `nav`/`header`. Menus, dialogs, fixed overlays and nav/header content are excluded, and hidden text no toggle points at stays hidden. It runs up to 3 rounds for nested panels, capped at 300. When toggles were clicked, it waits 1 s first so closing animations finish. Decision D32; spec §3.4 and §10.2 updated.
- `meta.json` → `prep.panels_revealed` `{collapse, tab, disclosure}`, and the job panel shows the total. Old `meta.json` files still load.
- Manual check (scratch data dir) on the 3 real pages, visible chars before → after:
  - KFUPM: 6,315 → 120,447 (47 collapse panels);
  - KAUST entry-requirements: 4,192 → 10,444 (5 tabs);
  - EDISS country-specific: 5,406 → 43,534 (26 collapse panels + 1 already open = all 27).
  No menu, chat or consent text appeared.
- No schema change. No Claude calls.
- Tests: 259 (4 new). There are 3 browser fixtures, one per pattern: an accordion with mismatched `aria-expanded`, ARIA tabs in a `nav`, and a single-open accordion that animates closed. Each has decoys (a nav menu, a collapse no toggle points at, a chat dialog, a `display:none` paragraph) that must stay out of `visible_text.txt`.

## 2026-10-09 — add a source URL to an existing programme (`feat/add-source`)
- Tracker cards get **＋ Add source** (URL + role). It creates one `program_sources` row on that programme and starts a fetch job for only that source, then opens the usual job page. Same robots/delay/timeout rules; a URL another programme already snapshotted is reused, not fetched again. Existing sources and snapshots are untouched.
- Validation reuses `normalise_url` and the role check (`actions.parse_source`, now shared with the Add page). A URL already on this programme → 409 with the message on the card; the same URL on a different programme is allowed; bad URL/role → 422; the 10-URL limit applies.
- Cards list their sources (role, URL, latest outcome) in a collapsible "Sources" list. The tracker page now swaps 422 responses as well as 404/409.
- Spec §1.4 Flow A step 1 says where extra URLs are added; the "not built yet" note is gone.
- No schema change. No Claude calls.
- Tests: 255 (13 new; 2 use the browser, including a page whose URL has an apostrophe, like KAUST's `/study/master's-degree`). Manual check on a scratch data dir against the real KAUST page: saved, then reused by a second programme.

## 2026-10-09 — docs: offerings + v2 page discovery (`docs/discovery-offerings`)
- Direction change after hand-labelling KAUST: one programme's facts span 5–6 pages on two subdomains, and one page covers MS, MS/PhD and PhD.
- D30: the user tracks **offerings** (programme + degree level), not pages; every value says which degree levels it applies to, or "not stated". Table changes decided in step 3.
- D31: v2 **page discovery agent** — one URL → on-site links → relevant pages → snapshots → offerings. Same parent domain, page/depth caps, robots + delay + fetch-once, per-job cost guard; its only tool fetches links code already found. Measured by page recall, offering recall, pages and cost per discovery. D5's table gains a row.
- Spec v0.5: module 1 (v1 → v2) vs module 8, Flow A (v2), v2 table row, step 3 row, `discover/` in §3.2, offerings note in §4.1, label `sources`/`missing_sources` as discovery ground truth (§8.1), defence layer 5 (§10.2), open question 6.
- Project status: KAUST schema friction (9 items) listed under step 3; new open question on the label format for several offerings; next steps reordered (add-a-source-URL first).
- No code or test changes.

## 2026-10-09 — v1 step 7 (part): Tracker + status lifecycle (`feat/tracker`)
- `core/tracker/status.py`: transition table per spec §6 plus undo result (`ADMITTED`/`REJECTED` → `APPLIED`) and withdraw (`APPLIED` → `DROPPED`, default reason "withdrawn"); restore → `TARGETING`; invalid transitions raise. Filters: Targeting (default), Saved, Applied (incl. results), Dropped, All.
- Every status change records `status_changed_at`; restore clears the drop reason.
- **Tracker** page: cards with name, university and country ("—" until step 4), host, status + date, source count, latest fetch outcome per source, link to snapshots, and an empty marked slot for the funding badge / eligibility warning (step 4). Buttons follow the status; HTMX swaps the card and updates tab counts out of band; results ask to confirm.
- Permanent delete (dropped programmes only, confirm step, refused while a fetch job runs): removes rows and unused snapshot folders; a snapshot another programme reuses is handed over (oldest reusing row promoted); `llm_calls` kept with ids cleared. Decisions D28, D29.
- Errors are shown on the card: a 409 (e.g. a stale page) or 404 returns the card re-read from the DB with the message on it (or a "no longer exists" note), with fresh buttons and counts; the tracker page tells htmx to swap 404/409; other failures (5xx, network) show a fallback message on the card. Non-HTMX requests still get a plain 409/404.
- No schema change. No Claude calls.
- Tests: 242 (95 new, none need a browser). Manual check on a throwaway instance (scratch data dir; example.com/.org/.net): full lifecycle, delete with a shared admissions snapshot, fetch success rate unchanged.

## 2026-10-08 — snapshot meta records the browser (`feat/snapshot-browser-info`)
- `meta.json` gains `browser: {name, version, channel}` (e.g. `chromium`, `141.0.7390.37`, `null` = Playwright's bundled build, or `msedge`/`chrome`), so a change in captured text can be traced to a browser upgrade or channel switch.
- Set for fetched pages and offline-rendered HTML imports; `null` for robots.txt refusals and PDF uploads (no browser rendered them). Older `meta.json` files load unchanged (`browser` defaults to `null`).
- `snapshot_source(..., channel=...)` is now a required keyword, so the recorded channel can't silently disagree with the launched browser.
- Tests: 147 (3 new browser-free; browser tests extended). All pass locally against Edge with `VERIGRAD_REQUIRE_BROWSER=1`.

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
