"""Tracker page: programme cards, status actions (HTMX), add a source, re-fetch all sources and
permanent delete. Thin: logic is in core/tracker/ and core/fetch/actions.py.

Errors on HTMX requests keep their status code (404/409) but return the card, re-read from the
DB, with the message on it (or a "no longer exists" note); tracker.html tells htmx to swap
those codes. Plain requests get a plain-text 409 or a 404."""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from verigrad.core.fetch import actions
from verigrad.core.store.models import SourceRole
from verigrad.core.tracker import service
from verigrad.core.tracker.status import InvalidTransition, TrackerAction, TrackerFilter
from verigrad.web.routes import context, templates

router = APIRouter()

NOT_FOUND = "This programme no longer exists (it may have been deleted in another tab)."


@router.get("/tracker", response_class=HTMLResponse)
def tracker_page(request: Request, filter: str | None = None) -> HTMLResponse:
    current = TrackerFilter.parse(filter)
    engine = request.app.state.engine
    values = context(request, "/tracker") | {
        "cards": service.list_cards(engine, current),
        "tabs": service.tabs(engine),
        "current_filter": current,
    }
    return templates.TemplateResponse(request, "tracker.html", values)


@router.get("/tracker/programs/{program_id}/card", response_class=HTMLResponse)
def card(request: Request, program_id: int, filter: str | None = None) -> Response:
    current = TrackerFilter.parse(filter)
    found = service.get_card(request.app.state.engine, program_id)
    if found is None:
        return _error(request, program_id, current, NOT_FOUND, 404)
    values = {"card": found, "current_filter": current}
    return templates.TemplateResponse(request, "_program_card.html", values)


@router.get("/tracker/programs/{program_id}/delete", response_class=HTMLResponse)
def delete_confirm(request: Request, program_id: int, filter: str | None = None) -> Response:
    current = TrackerFilter.parse(filter)
    preview = service.delete_preview(request.app.state.engine, program_id)
    if preview is None:
        return _error(request, program_id, current, NOT_FOUND, 404)
    values = {"preview": preview, "current_filter": current}
    return templates.TemplateResponse(request, "_delete_confirm.html", values)


@router.post("/tracker/programs/{program_id}/delete", response_model=None)
def delete(
    request: Request,
    program_id: int,
    filter: Annotated[str, Form()] = "",
) -> Response:
    current = TrackerFilter.parse(filter)
    engine, settings = request.app.state.engine, request.app.state.settings
    preview = service.delete_preview(engine, program_id)
    try:
        result = service.delete_program(engine, settings, program_id)
    except LookupError:
        return _error(request, program_id, current, NOT_FOUND, 404)
    except (service.NotDropped, service.JobRunning) as exc:
        return _error(request, program_id, current, f"Not deleted: {exc}.", 409)
    if not _is_htmx(request):
        return RedirectResponse(f"/tracker?filter={current.value}", status_code=303)
    values = {
        "program_id": program_id,
        "name": preview.card.name if preview else f"#{program_id}",
        "result": result,
        "tabs": service.tabs(engine),
        "current_filter": current,
    }
    return templates.TemplateResponse(request, "_deleted.html", values)


@router.post("/tracker/programs/{program_id}/sources", response_model=None)
def add_source(
    request: Request,
    program_id: int,
    url: Annotated[str, Form()] = "",
    role: Annotated[str, Form()] = SourceRole.ADMISSIONS.value,
    filter: Annotated[str, Form()] = "",
) -> Response:
    """Attach a URL to this programme and go to its fetch job page (same flow as /add)."""
    current = TrackerFilter.parse(filter)
    engine, runner = request.app.state.engine, request.app.state.runner
    try:
        job_id = actions.add_source(engine, runner, program_id, url, role)
    except LookupError:
        return _error(request, program_id, current, NOT_FOUND, 404)
    except actions.SourceRejected as exc:
        form = {"url": url, "role": role}
        return _error(request, program_id, current, str(exc), exc.status_code, form)
    return _to_job(request, job_id)


@router.post("/tracker/programs/{program_id}/refetch", response_model=None)
def refetch_all(request: Request, program_id: int, filter: Annotated[str, Form()] = "") -> Response:
    """One forced fetch job over all of this programme's sources; go to its job page."""
    current = TrackerFilter.parse(filter)
    engine, runner = request.app.state.engine, request.app.state.runner
    try:
        job_id = actions.refetch_program(engine, runner, program_id)
    except LookupError:
        return _error(request, program_id, current, NOT_FOUND, 404)
    except actions.JobAlreadyActive as exc:
        message = f"Not started: {exc}. Open the snapshots link to follow it."
        return _error(request, program_id, current, message, 409)
    return _to_job(request, job_id)


@router.post("/tracker/programs/{program_id}/{action}", response_model=None)
def act(
    request: Request,
    program_id: int,
    action: str,
    reason: Annotated[str, Form()] = "",
    filter: Annotated[str, Form()] = "",
) -> Response:
    current = TrackerFilter.parse(filter)
    try:
        tracker_action = TrackerAction(action)
    except ValueError:
        return _error(request, program_id, current, f"Unknown action: {action}.", 404)
    engine = request.app.state.engine
    try:
        updated = service.apply_action(engine, program_id, tracker_action, reason)
    except LookupError:
        return _error(request, program_id, current, NOT_FOUND, 404)
    except InvalidTransition as exc:
        message = f"Not changed: {exc}. The buttons below show what is possible now."
        return _error(request, program_id, current, message, 409)
    if not _is_htmx(request):
        return RedirectResponse(f"/tracker?filter={current.value}", status_code=303)
    values = {"card": updated, "tabs": service.tabs(engine), "current_filter": current}
    return templates.TemplateResponse(request, "_card_update.html", values)


def _error(
    request: Request,
    program_id: int,
    current: TrackerFilter,
    message: str,
    status_code: int,
    source_form: dict[str, str] | None = None,
) -> Response:
    if not _is_htmx(request):
        if status_code == 404:
            raise HTTPException(status_code=404, detail=message)
        return PlainTextResponse(message, status_code=status_code)
    engine = request.app.state.engine
    found = service.get_card(engine, program_id)
    values = {"tabs": service.tabs(engine), "current_filter": current, "error": message}
    if found is None:
        values |= {"program_id": program_id}
        return templates.TemplateResponse(request, "_program_gone.html", values, status_code=404)
    values |= {"card": found, "source_form": source_form}
    return templates.TemplateResponse(request, "_card_update.html", values, status_code=status_code)


def _to_job(request: Request, job_id: int) -> Response:
    location = f"/add/jobs/{job_id}"
    if _is_htmx(request):
        return Response(status_code=204, headers={"HX-Redirect": location})
    return RedirectResponse(location, status_code=303)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"
