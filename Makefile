# Each recipe is a single `uv run ...` line so it works from PowerShell, cmd or Git Bash.
# Windows: install make once with `winget install ezwinports.make`.

.PHONY: dev test test-live eval lint

dev:
	uv run uvicorn verigrad.web.app:app --reload

test:
	uv run pytest

test-live:
	uv run pytest -m live

eval:
	uv run python -m verigrad.evals

lint:
	uv run ruff check --fix .
	uv run ruff format .
