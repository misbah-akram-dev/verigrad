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
                 llm ──── wraps every Claude call: retries + cost/latency logging
```

## Modules (`src/verigrad/core/`)
| Module | Responsibility | Status |
|---|---|---|
| `llm/` | Claude client wrapper: retries, logging to `llm_calls`, `run_eval()` | Not started |
| `store/` | SQLite models and repository | Not started |
| `fetch/` | Snapshots, accordion expansion, block detection, manual import | Not started |
| `extract/` | Prompts (versioned) + schema → structured extraction | Not started |
| `verify/` | Checks 1–4 (v1), 5 (v2) → confidence | Not started |
| `jobs/` | Background jobs + progress for the UI | Not started |
| `plan/` | Backwards planning, timezones, `.ics` | Not started |
| `spider/` | (v2) Selector generation/repair, re-checks | Not started |

## Web (`src/verigrad/web/`)
Pages: Add · Programme · Review · Tracker · Plan · Dashboard · Costs

## Key decisions
| Date | Decision | Why |
|---|---|---|
| 2026-10-05 | Web app (FastAPI + HTMX), no CLI except `make eval` | Better demo; evals still need a command for CI |
| 2026-10-05 | Extraction runs on saved snapshots only | Repeatable evals, offline debugging, base for v2 spider |
| 2026-10-05 | Confidence set by code checks, not the model | Verifiable; calibration is measurable |
| 2026-10-05 | No proxies; blocked pages → manual upload | Tiny volume; polite fetching |
