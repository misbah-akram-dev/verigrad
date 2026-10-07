"""Add page, fetch-job panel, re-fetch, manual import and snapshot files. Thin: logic is in
core/fetch/actions.py and core/fetch/manual_import.py."""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from verigrad.core.fetch import actions
from verigrad.core.store.models import SourceRole
from verigrad.web.routes import context, templates

router = APIRouter()

ROLES = [role.value for role in SourceRole]

# Untrusted snapshot content is never rendered as HTML on our origin.
_SAFE_TYPES = {
    ".html": "text/plain; charset=utf-8",
    ".htm": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".pdf": "application/pdf",
}
_SAFE_HEADERS = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"}


@router.get("/add", response_class=HTMLResponse)
def add_page(request: Request) -> HTMLResponse:
    rows = [{"url": "", "role": SourceRole.PROGRAM.value}]
    return _form(request, rows=rows)


@router.get("/add/source-row", response_class=HTMLResponse)
def source_row(request: Request) -> HTMLResponse:
    row = {"url": "", "role": SourceRole.ADMISSIONS.value}
    return templates.TemplateResponse(request, "_source_row.html", {"row": row, "roles": ROLES})


@router.post("/add", response_model=None)
def add_submit(
    request: Request,
    name: Annotated[str, Form()] = "",
    url: Annotated[list[str], Form()] = [],  # noqa: B006 — FastAPI form default
    role: Annotated[list[str], Form()] = [],  # noqa: B006
) -> Response:
    rows = [{"url": u, "role": r} for u, r in zip(url, role, strict=False)] or [
        {"url": "", "role": SourceRole.PROGRAM.value}
    ]
    add_request, errors = actions.parse_add_form(name, url, role)
    if errors:
        return _form(request, rows=rows, name=name, errors=errors, status_code=422)
    outcome = actions.add_programme(request.app.state.engine, request.app.state.runner, add_request)
    if outcome.job_id is None:
        return _form(
            request,
            rows=rows,
            name=name,
            errors=outcome.errors,
            duplicate_job_id=outcome.duplicate_job_id,
            status_code=409,
        )
    return RedirectResponse(f"/add/jobs/{outcome.job_id}", status_code=303)


@router.get("/add/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: int) -> HTMLResponse:
    view = _view(request, job_id)
    return templates.TemplateResponse(request, "job.html", context(request, "/add") | {"job": view})


@router.get("/add/jobs/{job_id}/panel", response_class=HTMLResponse)
def job_panel(request: Request, job_id: int) -> HTMLResponse:
    view = _view(request, job_id)
    return templates.TemplateResponse(request, "_job_panel.html", {"job": view})


@router.post("/sources/{source_id}/refetch")
def refetch(request: Request, source_id: int) -> RedirectResponse:
    job_id = actions.refetch_source(request.app.state.engine, request.app.state.runner, source_id)
    if job_id is None:
        raise HTTPException(status_code=404, detail="source not found")
    return RedirectResponse(f"/add/jobs/{job_id}", status_code=303)


@router.get("/snapshots/{snapshot_id}/files/{relative:path}")
def snapshot_file(request: Request, snapshot_id: int, relative: str) -> FileResponse:
    path = actions.snapshot_file(
        request.app.state.engine, request.app.state.settings, snapshot_id, relative
    )
    if path is None:
        raise HTTPException(status_code=404, detail="file not found")
    media_type = _SAFE_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers=_SAFE_HEADERS)


def _view(request: Request, job_id: int) -> actions.JobView:
    view = actions.job_view(request.app.state.engine, request.app.state.settings, job_id)
    if view is None:
        raise HTTPException(status_code=404, detail="job not found")
    return view


def _form(
    request: Request,
    rows: list[dict[str, str]],
    name: str = "",
    errors: list[str] | None = None,
    duplicate_job_id: int | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    values = {
        "rows": rows,
        "roles": ROLES,
        "name": name,
        "errors": errors or [],
        "duplicate_job_id": duplicate_job_id,
    }
    return templates.TemplateResponse(
        request, "add.html", context(request, "/add") | values, status_code=status_code
    )
