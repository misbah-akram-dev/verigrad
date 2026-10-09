# Decisions — the reasoning behind the design

> Why things are the way they are. `docs/architecture.md` lists *what* was decided (one line each); this file records *why*, including options we rejected. Add an entry whenever a decision is made outside the code (planning chats, reviews). Newest first within each section.

---

## 1. Scope

### D30 — The user tracks offerings, not pages (2026-10-09)
**Decision:** Extraction returns a list of **offerings** found across a programme's pages. An offering is one application a person can submit: programme name + degree level (MS, MS/PhD, PhD…) + its intakes/deadlines, requirements, fees and funding. I tick the offerings I care about; those go to the Tracker. Snapshots and pages stay as evidence behind each value, never a step I have to go through.
**Why:** Hand-labelling KAUST showed one programme's facts spread over 5–6 pages on two subdomains, and KAUST's timelines page covers MS, MS/PhD and PhD at once (Round 1 is PhD-only). One-URL-one-programme forces a wrong identity. Pages are shared between offerings, which is already supported: a shared URL is fetched once and reused (D22).
**Applicability:** Facts may come from university-wide pages (requirements, duration, fees) rather than a programme page. Each value says which degree levels it applies to, or "not stated" — never an assumed "applies to all".
**Impact:** Step 3's schema change designs extraction output as `offerings: list[Offering]` with per-value applicability. Tracker and status work on offerings. Exact table changes are decided in step 3 (plan mode), not here.

### D1 — Paste-a-URL instead of a searchable programme database (2026-10-05)
**Decision:** v1 adds programmes by pasting URLs. No study-portal-style search over thousands of programmes.
**Why:** A searchable database means building and maintaining a large scraper of third-party portals — a scraping project, not an AI one, with terms-of-service risk and constant data upkeep. It would consume the month without demonstrating AI engineering.
**Instead:** v2 (optional) — an agent uses the Claude web-search tool to *find* candidate programme URLs from a description, which then go through normal extraction.

### D2 — Autofill narrowed to a "fill plan", moved to v3 (2026-10-05)
**Decision:** The form helper produces a mapping (form field → my value, converted to the form's format, with confidence). Filling 2–3 portals with Playwright is optional; I always submit myself.
**Why:** Real portals mean logins, CAPTCHAs and multi-page forms; browser automation there is fragile and should be a last resort. The AI-interesting part is the mapping, and it is measurable (mapping accuracy on labelled forms).

### D3 — Gmail monitoring dropped (2026-10-05)
**Why:** Large integration, adds another untrusted input channel for prompt injection, and shows nothing new beyond what extraction + re-checks already show.

### D4 — Web app first; evals keep one command (2026-10-05)
**Decision:** FastAPI + Jinja2 + HTMX web app is the interface. No CLI except `make eval` / `python -m verigrad.evals`.
**Why:** A web review screen (value beside its highlighted source quote) demos far better than a terminal. Evals still need a command for development loops and CI. Streamlit rejected (awkward for background jobs and custom review layouts, looks like a prototype); React rejected (second language + build system, too much for a month).

---

## 2. Getting and reading pages

### D31 — Autonomous page discovery from one URL (v2) (2026-10-09)
**Decision:** I paste one URL. A discovery agent fetches it, collects its links, decides by itself which pages are relevant (deadlines, requirements, fees, funding, programme details), follows them and snapshots them; extraction then runs over all of them. I am never asked to choose pages.
**Guardrails:**
- Stays on the same site (same parent domain, e.g. `*.kaust.edu.sa`).
- Max pages per discovery job and max link depth are config values (e.g. 15 pages, depth 3).
- robots.txt, the per-domain delay and fetch-once reuse still apply (D8, D22, D23).
- The per-job cost guard (D17) covers the agent's Claude calls.
- The agent's only tool is "fetch this URL", restricted to links code has already found on fetched pages within the allowed domains, so a malicious page can't send it anywhere else or make it act. Page content stays untrusted data (D12).

**Transparency:** Each offering shows a collapsible "pages used" list with why each page was chosen. A manual "add a URL to this programme" fallback covers misses.
**Measured:** page recall (did it find the pages a human needed — the `sources` + `missing_sources` recorded in each hand label), offering recall (did it find every MS / MS-PhD / PhD offering), pages fetched and cost per discovery.
**Rejected:** showing me a list of candidate pages/snapshots to approve (I shouldn't have to judge pages); using web search for this (links on the university's own site are cheaper, deterministic and stay on-site — web search stays with the separate "Find programmes" module 8).
**Relation to D1/D5:** Page discovery within a site is link-following, not web search; D1's web-search discovery is about finding *new* programmes. D5's table has a row for each.

### D21 — Fetch jobs run on their own thread and event loop (2026-10-07)
**Decision:** A single worker thread runs every background job in its own `asyncio.Runner`, with a ProactorEventLoop on Windows, using Playwright's async API. Playwright never runs on FastAPI's event loop.
**Why:** With `--reload` (`make dev`), uvicorn runs FastAPI on a SelectorEventLoop on Windows, which can't start Playwright's driver subprocess. Owning the loop works whatever uvicorn picks. One worker also runs jobs one at a time, which suits polite fetching. Rejected: the sync API in a thread (works today, but depends on the default loop policy) and running Playwright in FastAPI's loop (breaks on Windows).

### D22 — Fetch once per URL; shared pages are reused; re-fetch is explicit (2026-10-07)
**Decision:** If a URL already has a SUCCESS or MANUAL_IMPORT snapshot, any other source with that URL gets a row pointing at the same folder — no new request. Only a `program`-role URL identifies a duplicate programme; admissions, scholarship and fees pages may be shared (e.g. KAUST's central admission-timelines page). A per-source **Re-fetch** takes a new snapshot and keeps the old one.
**Why:** D8's "fetch once and reuse", applied to how universities actually publish: several programmes point at the same central page. Reused rows are not counted as fetch attempts, so the success rate stays honest.

### D23 — robots.txt by RFC 9309; disallow means BLOCKED (2026-10-07)
**Decision:** 2xx → apply the rules; 4xx → no rules; 5xx → disallow everything; a disallowed page is `BLOCKED` (`robots_disallowed`), so the upload box appears. A network-level failure fetching robots.txt (DNS, refused) does not count as a disallow: the page fetch then fails with its real reason. `Crawl-delay` is honoured when longer than our delay. The delay is per university domain, not per host.
**Why:** Respecting robots.txt is part of being polite (D8), and "blocked → ask the user" already has a path. Treating an unreachable robots.txt as "disallow" would ask the user to upload a copy of a mistyped URL. Per-domain delay: `cs.kaust.edu.sa` and `admissions.kaust.edu.sa` are the same university's servers.

### D24 — Same-site JSON and PDFs only; skipped links recorded (2026-10-07)
**Decision:** JSON responses and linked PDFs are saved only from the page's parent domain (`ms.kfupm.edu.sa` ~ `www.kfupm.edu.sa`), with caps (50 × 2 MB JSON, 10 × 20 MB PDFs). Everything skipped is listed in `meta.json` with a reason (`off_site`, `cap`, `too_large`, `robots_*`, …).
**Why:** Third-party JSON is analytics and chat widgets, not programme data. Off-site PDFs (e.g. EDISS partner universities) are skipped for now; if one matters, it can be added as an extra source URL, since sources may be on any domain.

### D25 — Manual HTML imports are rendered offline (2026-10-07)
**Decision:** An uploaded HTML page is rendered in Chromium with JavaScript off and every network request aborted, producing `visible_text.txt` and a screenshot like a fetched page.
**Why:** Keeps uploads on the same footing as fetched pages, so the v2 hidden-text check also works on them. Offline + no JS means an uploaded page can't call out or run code. Trade-off: without its external CSS, some styled-hidden text may count as visible.

### D26 — Snapshot HTML is never rendered on our origin (2026-10-07)
**Decision:** The file route serves only files inside the snapshot's own folder (resolved-path check), and serves saved HTML as `text/plain` with `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`.
**Why:** Saved pages are untrusted (D12). Rendering them on the app's origin would let a page's scripts act against the app.

### D27 — Optional installed browser channel (2026-10-07)
**Decision:** `VERIGRAD_BROWSER_CHANNEL` (empty by default) can point Playwright at an installed Edge or Chrome instead of the bundled Chromium.
**Why:** On some networks `playwright install chromium` can't download the browser. Edge ships with Windows and behaves the same for our purposes; the default stays the bundled Chromium (D8).

### D5 — Tool roles: Playwright fetches, Claude API extracts, web search only discovers (2026-10-07)
| Stage | Tool | Role |
|---|---|---|
| Fetch (step 2) | **Playwright** | Opens each URL in a real browser and saves a snapshot. No AI. |
| Extract (step 4) | **Claude Messages API** | Reads the *saved* snapshot text and returns structured fields + source quotes. No web access. |
| Verify (step 5) | **Code** | Checks Claude's output against the snapshot. |
| Re-check (v2) | **Selector spider** | Agent-written selectors re-run cheaply; Claude re-reads only changed fields. |
| Page discovery (v2) | **Claude + domain-restricted fetch** | From one pasted URL, follows on-site links already found on fetched pages to the pages that hold the programme's facts. Not web search (D31). |
| Find programmes (v2, optional) | **Claude web search** | Finds candidate programme URLs. |

**Why not let Claude web-fetch pages during extraction:** (a) evals need frozen inputs — the same snapshot gives comparable scores over time; (b) verification needs to check quotes against exactly what Claude saw; (c) no tools during extraction means a malicious page can't make Claude act; (d) Playwright fetching is free, Claude fetching costs tokens; (e) web fetch gives no screenshot, no visibility data (needed for the hidden-text check) and no HTML for the v2 spider.
**Possible later experiment:** web fetch as a fallback for blocked pages, measured against Playwright on the same pages.

### D6 — Snapshots: save everything, extract only from saved copies (2026-10-05)
**Decision:** Each fetch saves rendered HTML, clean text, visible text, full screenshot, JSON responses and linked PDFs. Extraction and evals never touch live pages.
**Why:** Repeatable evals, offline debugging, base for the v2 spider and change detection, and evidence for the review screen. Separate `visible_text.txt` (what a person sees) makes the v2 hidden-text check nearly free.

### D7 — Several source URLs per programme (2026-10-07)
**Decision:** A programme has many `program_sources` (program / admissions / scholarship / fees …), all snapshotted and extracted together; every quote records which URL it came from.
**Why:** Found on the first real programmes: KAUST keeps deadlines on a central admissions page; EDISS splits admission, requirements and scholarships across pages; KFUPM has separate self-funded and scholarship routes. One-URL-per-programme would silently miss deadlines.

### D8 — Polite fetching; no proxies; blocked → manual upload (2026-10-05)
**Decision:** Real Chromium from a home IP, robots.txt respected, per-domain delay, fetch once and reuse. Challenge pages / login walls → `BLOCKED` → I save the page from my browser and upload it.
**Why:** Volume is tiny (~30 pages, then weekly re-checks of targeted programmes); university sites are lightly protected. Proxies and evasion add cost and undermine the portfolio story. "Blocked" means "ask the user", not "work around it". Fetch success rate is reported as a metric.

### D9 — Agent-written selectors are v2, checked against *confirmed* values (2026-10-05)
**Decision:** After a programme's values are reviewed, an agent writes a selector per field (starting from the element containing the verified quote), runs it on the snapshot, and repairs it until its output matches the **user-confirmed** value. Weekly re-checks run selectors; Claude re-extracts only changed fields.
**Why:** Selectors make re-checks free and deterministic and give change detection for free. But they only reproduce the value they were checked against — validating against unreviewed LLM output would lock in wrong answers. Selectors return text, not meaning, so prose fields still need parsing. At ~20 programmes the saving is small; the value is reliability, drift detection and the agent-loop demo.

---

## 3. Verification and evals

### D10 — Claude proposes, code verifies; five check layers (2026-10-05)
**Decision:** Claude never sets confidence. Code runs: (1) value exists in source (normalised), (2) value is inside its quote and the quote is in the source, (3) sources agree, (4) context & ambiguity — several candidates? does the quote mention the right intake / applicant type / programme?, (5, v2) quote comes from visible text.
**Why:** Checks 1–3 catch invented or misread values, but the most common real error is **picking the wrong real value** — e.g. the EU deadline instead of the international one, a previous intake's dates (EDISS), a PhD-only round (KAUST), another programme's deadline on the same page (KFUPM). Those pass existence checks in every source; only check 4 catches them. Calibration ("HIGH was right 98% of the time") makes the levels trustworthy and measurable.

### D11 — Labelling: hand-label 5, agent drafts the rest, I confirm every value (2026-10-05)
**Why:** If the same model both labels and extracts, shared mistakes stay invisible and the accuracy number is meaningless. So: 5 programmes labelled by hand first (also tests the schema early); remaining drafts come from a **different, stronger model (Opus)** than the extractor (Sonnet); every value is confirmed by me; agent drafts are compared against my hand labels to measure how far to trust them. Labels are needed only for extraction (and later, separately, for form mapping) — display, planning and reminders are plain code tested with unit tests.

### D12 — Prompt-injection defence is in scope (2026-10-05)
**Why:** Pages are untrusted text written by others; hidden instructions can plant wrong deadlines (v1) or wrong actions (v3 form helper). Handling untrusted input is a core requirement for any agent that reads the web. Layers: page content as delimited data; every value must quote the page; no acting tools during extraction; v2 visibility check. Collapsed accordions are expanded before snapshotting so legitimately hidden content isn't flagged.

---

## 4. Data and preferences

### D29 — Status lifecycle: results can be corrected, applications withdrawn (2026-10-09)
**Decision:** Spec §6 plus two moves: **undo result** (`ADMITTED`/`REJECTED` → `APPLIED`) and **withdraw** (`APPLIED` → `DROPPED`, reason "withdrawn" if none given). Restore always goes to `TARGETING`. Every other transition is rejected. Setting a result or marking applied asks for confirmation. The tracker's **Applied** filter shows `APPLIED`, `ADMITTED` and `REJECTED`; the badge says which.
**Why:** A results click is easy to get wrong, and a strict one-way lifecycle would leave no fix short of editing the DB. Withdrawing is a real step after applying (another offer accepted). Restoring to `TARGETING` rather than the old status keeps the rule simple; an applied programme can be re-marked in one click. Results belong with applications, so they don't need their own tab.

### D28 — Permanent delete: dropped only; shared snapshots handed over; spend kept (2026-10-09)
**Decision:** Delete is offered only on `DROPPED` programmes, behind a confirmation that lists what will be removed and kept, and is refused while a fetch job for the programme runs. It removes the programme's rows and snapshot folders in one transaction, except: (a) an original snapshot another programme reuses (D22): the oldest reusing row becomes the original, the other reusers point at it, and the folder stays; (b) `llm_calls` rows stay, with `program_id`/`job_id` cleared. A folder is removed only when no remaining row points at it, and only inside `data/snapshots/`.
**Why:** Two steps (drop, then delete) make accidental deletion unlikely. Promoting the reusing row keeps the shared page available to the other programme and leaves the fetch success rate unchanged (the shared fetch still counts once). Blocking the delete instead would tie programmes together. Cost rows record money actually spent; deleting them would make the Costs page undercount. No schema change was needed.

### D13 — Extract everything; the profile chooses (2026-10-07)
**Decision:** Extraction records every deadline, funding option and eligibility restriction. A deterministic profile then picks: applicant type = international / non-EU; degree level = Master's; funding = fully funded first, otherwise whatever exists (partial → fee waiver → self-funded); programmes whose stated restrictions exclude me are flagged "not eligible"; unstated restrictions show "unknown".
**Why:** Keeps evals honest (reading the page vs choosing for me are measured separately), lets check 4 see every candidate, and lets preferences change without re-extraction. Real cases: EDISS rounds differ by *funding route*; KAUST has a PhD-only round; KSU MSc AI is nationals-only; another candidate was single-gender with a religious requirement.

### D14 — App state and preferences live in SQLite, never in AI memory (2026-10-05)
**Why:** Tracker status and profile rules must be exact and repeatable — looked up, not recalled. AI memory (v3) is reserved for soft preferences used in suggestions ("prefer Germany").

### D15 — Funding shown on every programme (2026-10-07)
**Decision:** Programme page has a Funding section with evidence; tracker cards show a badge: Fully funded / Partial / Self-funded / Unknown–not yet published.
**Why:** Funding is my top filter. "Not yet published" (e.g. KFUPM scholarship page before opening) must show as unknown, never guessed; v2 re-checks alert when it changes.

---

## 5. Models and cost

### D16 — Models: Sonnet extracts, Haiku compares, Opus drafts labels (2026-10-06)
**Why:** Sonnet 5.5 is about half Opus's cost (~$0.06 vs ~$0.12 per typical programme) and fits the per-job budget; Haiku 4.5 gives the cheap-model comparison for the demo; Opus drafting labels keeps the labeller independent of the extractor (D11). Fable is out of scope (top-tier price, not needed). If Sonnet's accuracy is insufficient, an Opus run becomes a measured third comparison rather than a guess. The model is one `.env` value, so switching is trivial.

### D17 — Per-job budget, estimate logged next to actual (2026-10-06)
**Decision:** `VERIGRAD_MAX_COST_PER_JOB` (default $0.30). Guard = spend so far on this job + this call's estimate (chars/4 input + expected output). Unknown models raise instead of logging $0.
**Why:** A per-programme lifetime budget would be exhausted by repeated evals and re-extractions. $0.10 was too tight for Sonnet on pages with large PDFs. Logging `estimated_cost_usd` lets us report estimate accuracy and later compare against the token-counting endpoint.

### D18 — Expected spend (2026-10-06)
Estimates at Sonnet 5.5 ($2 / $10 per M tokens), ~20k input + ~2k output per programme:
- **Personal use after v1:** ~$1–5 / month (≈20 new programmes, re-extractions, re-checks via selectors).
- **Build month:** ~$15–80, almost all from eval runs (~$2 per 30-page run; ~$1 with the Batch API).
- **Levers:** Batch API for evals (−50%), a 10-page quick eval while iterating, CI evals on PRs only, prompt caching for the fixed system prompt + schema.
API usage is billed to the Console key in `.env`, separately from the Claude subscription used for Claude Code.

---

## 6. Workflow

### D19 — Context lives in the repo, not in chats (2026-10-07)
**Decision:** Planning and second opinions happen in a separate Claude chat; every decision is written into `spec.md`, `docs/architecture.md`, `docs/programs.md` or this file before building. Claude Code starts each step in a fresh session that reads `CLAUDE.md` + docs.
**Why:** Chats aren't shared between tools or sessions; files are. Fresh sessions avoid stale context.

### D20 — One branch + PR per step; plan mode for code steps (2026-10-06)
**Why:** `main` stays stable; every change is reviewed in a PR diff; plans are reviewed before code is written. Docs-only changes can skip plan mode.
