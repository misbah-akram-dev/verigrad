# Verigrad

**AI assistant that extracts masters program deadlines and requirements from university pages and PDFs, with source quotes, verified confidence and evals.**

> 🚧 Work in progress — AI-engineering portfolio project. See [`spec.md`](spec.md) for the full plan and [`docs/project-status.md`](docs/project-status.md) for progress.

## What it does
1. **Add a programme** — paste a URL; get deadlines (in PKT), requirements, fees and documents.
2. **Every value is evidenced** — each comes with the exact source sentence and a confidence level set by code checks, not by the model.
3. **Check & confirm** — only doubtful values go to a review screen.
4. **Track and plan** — shortlist programmes and get a backwards task plan with a calendar export.
5. **Measured** — an eval set of real programme pages reports accuracy, calibration and cost per programme.

## Why it's interesting
The core problem — reliable structured extraction from messy, inconsistent web pages and PDFs — is the same one behind enterprise document ingestion. The project focuses on the production parts: verification, evals, cost tracking, failure handling and prompt-injection defence.

## Status
| Milestone | Scope | Status |
|---|---|---|
| v1 | Extraction engine + web app + evals | In progress (step 1/8: foundation done) |
| v2 | Change detection, self-verifying spider, injection defence, CI evals | Planned |
| v3 | MCP server, form helper | Planned |

## Results
_Eval numbers will be published here as milestones land._

## Getting started
Requires [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you) and `make`
(Windows: `winget install ezwinports.make`, then open a new terminal).

```sh
uv sync                    # install dependencies
cp .env.example .env       # PowerShell: Copy-Item .env.example .env
make dev                   # http://127.0.0.1:8000
```

The app starts without an API key; add `ANTHROPIC_API_KEY` to `.env` when you want Claude calls.

| Command | What it does |
|---|---|
| `make dev` | Run the web app with auto-reload |
| `make test` | Unit tests (no network, Anthropic client mocked) |
| `make test-live` | One real Claude call (~$0.001); skipped without a key |
| `make eval` | Evals on the golden set (placeholder until step 6) |
| `make lint` | `ruff check --fix` + `ruff format` |

Without `make`, run the same `uv run …` lines from the [Makefile](Makefile) directly.

## Docs
- [Spec](spec.md)
- [Architecture](docs/architecture.md)
- [Project status](docs/project-status.md)
- [Changelog](docs/changelog.md)
