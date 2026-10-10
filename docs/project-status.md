# Project status

> Read at the start of every session. Update at the end of every session.

**Current milestone:** v1 — Extraction engine + web app
**Target:** v1 demo by end of week 2 (may run into early week 3)
**Last session:** 2026-10-10 — re-fetch from Tracker cards (`feat/card-refetch`)

## v1 build steps (spec §2)
- [x] 1. Repo setup, LLM wrapper, extraction schema, SQLite store, FastAPI skeleton
- [x] 2. Fetch + snapshots + Add page + add a source to an existing programme — built; **remaining:** snapshot ~30 real programme pages (8 pages / 3 programmes so far; grow `docs/programs.md`)
- [ ] 3. Hand-label 5 programmes; fix schema — KAUST labelled (MS offering only); schema friction below
- [ ] 4. Extraction + Programme page
- [ ] 5. Verification checks 1–4 + confidence badges
- [ ] 6. Label remaining ~25; `make eval`; baseline; Dashboard page
- [ ] 7. Tracker + Review pages — **Tracker + status lifecycle done** (cards can add a source, re-fetch one source or re-fetch all); remaining: Review page (needs extraction), user profile (§6.1), funding badge on cards (needs step 4)
- [ ] 8. Planner + Plan page + `.ics`

### Step 3 — schema friction found while hand-labelling KAUST
To handle in step 3 (plan mode):
1. A deadline's meaning depends on several lines (section heading + eligibility line), so quotes must allow several lines.
2. "Tentative" dates: needs a flag on the deadline.
3. Application opening date (e.g. Round 2 opens 28 Sep 2026): no field.
4. Semester start date: no field.
5. Decision release dates: no field.
6. One page covers several degree levels: deadlines have `eligible_levels`, and requirements need it too (applicability).
7. Values from university-wide vs programme pages: need applicability/scope (D30).
8. Several facts per deadline needed notes as a list.
9. Programme identity: one URL → several offerings (D30).

## Numbers so far
| Metric | Value | Date |
|---|---|---|
| Field accuracy | — | |
| Calibration (H/M/L) | — | |
| Cost per programme | — | |
| Cost estimate accuracy (`estimated_cost_usd` vs `cost_usd`) | — | |
| Fetch success rate | **100%** — 8/8 sources (3 programmes), 0 blocked, 0 failed | 2026-10-07 |
| Tests | 266 (no internet; 27 of them drive a real browser against a local fixture site). CI runs all of them on every PR, browser tests included | 2026-10-10 |

### First real fetch run (2026-10-07, via the Add page, `make dev` with `--reload`)
Browser: installed Edge (`VERIGRAD_BROWSER_CHANNEL=msedge`), because the Chromium download was blocked in that session; same Chromium engine. Delay 3 s per domain.

| Programme · role | Outcome | HTML | Visible chars | JSON / PDFs | Accordions | Notes |
|---|---|---|---|---|---|---|
| KAUST · program `cs.kaust.edu.sa` | SUCCESS | 71 KB | 2,605 | 0 / 0 | none | Landing page; no deadlines (as expected) |
| KAUST · admissions (admission-timelines) | SUCCESS | 137 KB | 1,579 | 0 (8 off-site skipped) / 0 | 1 toggle; cookie banner | Captured "Spring 2027 … only open to PhD applicants" and Fall 2027 Round 2 deadline 3 January 2027 |
| EDISS · program | SUCCESS | 70 KB | 4,604 | 0 / 0 | 4 `<details>` | |
| EDISS · admissions `/admission/` | SUCCESS | 82 KB | 6,067 | 0 / 0 | 4 `<details>` | Shows the **previous** intake's rounds (Sept 2026) with Helsinki times — the known trap |
| EDISS · admissions `/admission-requirements/` | SUCCESS | 106 KB | 9,035 | 0 / 1 (2.7 MB CV template) | 4 + 9 toggles | |
| EDISS · scholarship | SUCCESS | 120 KB | 17,795 | 0 / 0 | 4 + 6 toggles | |
| KFUPM · program `ms.kfupm.edu.sa` | SUCCESS | 321 KB | 6,315 (text 120k: unopened panels; see below) | 0 (3 skipped) / 1 (rules & FAQ PDF) | none | Fall 2027 dates all "TBA" |
| KFUPM · scholarship (cgis) | SUCCESS | 20 KB | 2,077 | 0 / 0 | none | Not yet open |

No toggle navigated away; no expansion stopped. Slowest pages: 40–60 s total (navigation 30–40 s on KAUST/KFUPM).

### Panel-reveal fix (2026-10-10, scratch data dir, Edge)
Before the fix, `visible_text` missed real content on all 3 programmes. Real pages re-fetched with the fix:

| Page | Visible chars before → after | Panels revealed | Screenshot height (px) |
|---|---|---|---|
| KFUPM `ms.kfupm.edu.sa` | 6,315 → **120,447** (`text.txt` 120,562) | 47 collapse | 5,525 → 72,081 |
| KAUST entry-requirements | 4,192 → 10,444 | 5 tabs (English Language, GRE/PGAT…) | 3,490 → 5,850 |
| EDISS country-specific | 5,406 → 43,534 | 26 collapse (+1 already open = all 27) | 3,910 → 18,931 |

What is still only in `text.txt`: nav menus (KAUST), the cookie-consent dialog (EDISS) and line-wrap differences (KFUPM). KFUPM's "120k hidden text" was the 47 programme panels, not menus. The first run missed one EDISS section that was still animating closed; a 1 s wait after clicks fixed it. The old snapshots in `data/` predate the fix, so re-fetch them before labelling or extraction.

## Open questions
- ~~Golden-set programme list~~ Resolved: initial 3 in `docs/programs.md` (KAUST MS CS, EDISS Erasmus Mundus, KFUPM MS Data Science & Analytics), plus a Rejected section (nationality- and gender-restricted examples) kept as eligibility-restriction examples; target ~30 by step 6. Next step is still step 2.
- ~~Scholarships: v1 or v2?~~ Resolved: v1, via `funding_options` (spec §4.1); see `docs/changelog.md` 2026-10-07.
- Default extraction model + comparison model: provisionally `claude-sonnet-5-5` / `claude-haiku-4-5`; decide after first eval
- Is the chars/4 + expected-output estimate good enough for the per-job guard? Measure once extraction runs.
- Default `expected_output_tokens` (4000) and `VERIGRAD_MAX_COST_PER_JOB` ($0.30): tune after first real runs
- **Step 4 — extraction input:** send `visible_text.txt` + PDFs to Claude, not `text.txt`? KFUPM's `text.txt` was ~120k chars vs ~6.3k visible (it turned out to be 47 unopened programme panels, not menus); with the panel-reveal fix, visible text holds the real content. Cheaper and safer against hidden-text injection; keep `text.txt` for verification checks. Decide and record in `docs/decisions.md` at step 4.
  - **Before the panel-reveal fix (D32), `visible_text` missed real requirements on all 3 programmes:** KFUPM programme details, KAUST's English Language/GRE tabs, and EDISS's 26 of 27 country sections. Re-fetch before deciding.
  - **Cost:** KFUPM's `visible_text` grew from 6,315 to 120,447 chars (≈30k input tokens, ≈$0.06 at the Sonnet price in `pricing.py`) because all 47 programmes' panels are now revealed, though we track one. Decide in step 4: send the whole page and measure, or trim to the relevant offering's panel (the `data-verigrad-revealed` markers in `page.html` make panels easy to find). Re-check `VERIGRAD_MAX_COST_PER_JOB` ($0.30) against programmes with several large sources.
- **Label format for several offerings per programme:** decide in step 3 (KAUST label currently covers the MS offering only).
- **Card's "snapshots" link after Add source / Re-fetch:** it opens the latest job, which lists only the source that job fetched, not all of the programme's sources. After **Re-fetch all**, the latest job lists every source. Fine for now; revisit with the Programme page (step 4).
- **URL spelling variants:** `normalise_url` doesn't percent-decode, so `master's-degree` and `master%27s-degree` count as different URLs (duplicate check and snapshot reuse miss the match). Not seen in practice yet.
- **Shared-page staleness:** re-fetching a shared admissions page updates only that source; other programmes keep the older reused snapshot. Acceptable for v1; v2 weekly re-check should refresh all sources sharing a URL.

## Blockers / setup notes
- Local `.env`: rename `VERIGRAD_MAX_COST_PER_PROGRAM` → `VERIGRAD_MAX_COST_PER_JOB` (old name is ignored; default $0.30 applies). Optionally add `VERIGRAD_LLM_TIMEOUT_SECONDS=120`.
- Windows: `winget install ezwinports.make` for the Makefile.
- Browser for fetching (one-time): `uv run playwright install chromium`. If that download fails on your network, set `VERIGRAD_BROWSER_CHANNEL=msedge` in `.env` to use the installed Edge. Browser tests skip with a hint when no browser is available (CI sets `VERIGRAD_REQUIRE_BROWSER=1`, which makes them fail instead).
- Step-1 local DB was moved to `data/verigrad.step1.db` (schema changed; `create_all` doesn't add columns). Delete it once you don't need it.

## Where we left off
Step 1 done: uv project (Python 3.12), Makefile, `core/llm/` wrapper (retries honouring retry headers, per-job cost guard, `llm_calls` logging with estimated vs actual cost), extraction schema, SQLModel tables, settings, FastAPI skeleton with nav + placeholder pages. Merged via `feat/foundation`.
Docs-only update (`docs/funding-and-sources`): spec records multiple sources per programme (`program_sources`), extraction-never-filters rule, `funding_options` + `eligibility_restrictions` schema, and the user-profile + primary-deadline picker with "not eligible" flagging (spec §4.1, §4.2, §6.1, §7). `docs/programs.md` created with the first 3 golden-set programmes plus a Rejected section.
Step 2 built (`feat/fetch`): `program_sources`, Playwright snapshots (HTML, text, visible text, screenshot, same-site JSON/PDFs, `meta.json`), polite fetching (robots.txt, per-domain delay, fetch once + reuse, explicit Re-fetch), block detection, manual import, background job runner, Add page with polling panel. Decisions D21–D27 in `docs/decisions.md`.
CI (`chore/ci`): GitHub Actions runs `ruff check`, `ruff format --check` and the full `pytest` suite with Chromium installed on every PR and push to `main`; no secrets, `live` excluded. README has the status badge.
Snapshot provenance (`feat/snapshot-browser-info`): each `meta.json` records `browser: {name, version, channel}`. Snapshots taken before this have `null`.
Tracker (`feat/tracker`): `core/tracker/` (lifecycle rules, cards, permanent delete), Tracker page with HTMX actions and filters, confirmed delete for dropped programmes that keeps shared snapshot folders and cost rows (D28, D29). Built ahead of steps 3–6 because it doesn't need extraction; the card's funding/eligibility slot waits for step 4.
Direction change (`docs/discovery-offerings`, docs only): hand-labelling KAUST showed one programme's facts spread over 5–6 pages on two subdomains, and one page covering MS, MS/PhD and PhD. The user now tracks **offerings** (programme + degree level) with per-value applicability (D30), and v2 adds a **page discovery agent**: one URL → on-site pages → offerings (D31). Schema friction from the KAUST label is listed under step 3 above.
Add a source (`feat/add-source`): each Tracker card has **＋ Add source** (URL + role) that attaches one `program_sources` row to the existing programme and starts a fetch job for just that URL, through the normal job page (same robots/delay/timeout, same shared-URL reuse). A URL already on the programme is refused (409, on the card); the same URL on another programme is allowed and reused. Cards now list their sources with each one's latest outcome. Manual check on a scratch data dir: KAUST `admissions.kaust.edu.sa/study/master's-degree` (apostrophe in the path) saved, HTTP 200, 6.3k visible chars; adding it to a second programme reused the snapshot.
Panel-reveal fix (`fix/reveal-panels`): the fetcher now reveals hidden collapse/tab panels that a visible toggle points at, without clicking (D32). This fixes missing content on all 3 golden-set programmes; numbers are above.
Card re-fetch (`feat/card-refetch`): each source on a Tracker card has **↻ Re-fetch** (same as the job page's), and each card has **↻ Re-fetch all**: one forced job over all its sources, new snapshots, history kept, refused while a fetch job for that programme is active (D22 update).
Next:
1. Re-fetch the existing golden-set sources with **↻ Re-fetch all** on each card (old snapshots predate the fix). Then use Add source to snapshot KAUST's missing pages; continue labelling (and grow `docs/programs.md` toward ~30 programmes, which finishes step 2).
2. Step 3 — fix the schema (offerings, applicability, the friction list above).
