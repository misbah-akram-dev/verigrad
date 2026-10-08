# Project status

> Read at the start of every session. Update at the end of every session.

**Current milestone:** v1 — Extraction engine + web app
**Target:** v1 demo by end of week 2 (may run into early week 3)
**Last session:** 2026-10-08 — GitHub Actions CI added on `chore/ci` (lint + full test suite, browser tests run in CI)

## v1 build steps (spec §2)
- [x] 1. Repo setup, LLM wrapper, extraction schema, SQLite store, FastAPI skeleton
- [x] 2. Fetch + snapshots + Add page — built; **remaining:** snapshot ~30 real programme pages (8 pages / 3 programmes so far; grow `docs/programs.md`)
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
| Fetch success rate | **100%** — 8/8 sources (3 programmes), 0 blocked, 0 failed | 2026-10-07 |
| Tests | 144 (no internet; 21 of them drive a real browser against a local fixture site). CI runs all 144 on every PR, browser tests included | 2026-10-08 |

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
| KFUPM · program `ms.kfupm.edu.sa` | SUCCESS | 321 KB | 6,315 (text 120k: big hidden menus) | 0 (3 skipped) / 1 (rules & FAQ PDF) | none | Fall 2027 dates all "TBA" |
| KFUPM · scholarship (cgis) | SUCCESS | 20 KB | 2,077 | 0 / 0 | none | Not yet open |

No toggle navigated away; no expansion stopped. Slowest pages: 40–60 s total (navigation 30–40 s on KAUST/KFUPM).

## Open questions
- ~~Golden-set programme list~~ Resolved: initial 3 in `docs/programs.md` (KAUST MS CS, EDISS Erasmus Mundus, KFUPM MS Data Science & Analytics), plus a Rejected section (nationality- and gender-restricted examples) kept as eligibility-restriction examples; target ~30 by step 6. Next step is still step 2.
- ~~Scholarships: v1 or v2?~~ Resolved: v1, via `funding_options` (spec §4.1); see `docs/changelog.md` 2026-10-07.
- Default extraction model + comparison model: provisionally `claude-sonnet-5-5` / `claude-haiku-4-5`; decide after first eval
- Is the chars/4 + expected-output estimate good enough for the per-job guard? Measure once extraction runs.
- Default `expected_output_tokens` (4000) and `VERIGRAD_MAX_COST_PER_JOB` ($0.30): tune after first real runs
- **Step 4 — extraction input:** send `visible_text.txt` + PDFs to Claude, not `text.txt`? KFUPM's `text.txt` is ~120k chars (hidden menus) vs ~6.3k visible; accordions are already expanded, so visible text should hold the real content. Cheaper and safer against hidden-text injection; keep `text.txt` for verification checks. Decide and record in `docs/decisions.md` at step 4.
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
Next: grow `docs/programs.md` toward ~30 programmes and snapshot them (finishes step 2), then step 3 — hand-label 5 programmes and fix the schema.
