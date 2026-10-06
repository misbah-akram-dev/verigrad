# Verigrad

**AI assistant that extracts masters program deadlines and requirements from university pages and PDFs, with source quotes, verified confidence and evals.**

> 🚧 Work in progress — portfolio project for an AI-upskilling programme. See [`spec.md`](spec.md) for the full plan and [`docs/project-status.md`](docs/project-status.md) for progress.

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
| v1 | Extraction engine + web app + evals | Planned |
| v2 | Change detection, self-verifying spider, injection defence, CI evals | Planned |
| v3 | MCP server, form helper | Planned |

## Results
_Eval numbers will be published here as milestones land._

## Getting started
_Setup instructions will be added with the first runnable version._

## Docs
- [Spec](spec.md)
- [Architecture](docs/architecture.md)
- [Project status](docs/project-status.md)
- [Changelog](docs/changelog.md)
