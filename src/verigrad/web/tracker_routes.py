"""Tracker page: programme cards, status actions (HTMX) and permanent delete. Thin: logic is in
core/tracker/."""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from verigrad.core.tracker import service
from verigrad.core.tracker.status import InvalidTransition, TrackerAction, TrackerFilter
from verigrad.web.routes import context, templates

router = APIRouter()


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
def card(request: Request, program_id: int, filter: str | None = None) -> HTMLResponse:
    found = service.get_card(request.app.state.engine, program_id)
    if found is None:
        raise HTTPException(status_code=404, detail="programme not found")
    values = {"card": found, "current_filter": TrackerFilter.parse(filter)}
    return templates.TemplateResponse(request, "_program_card.html", values)


@router.get("/tracker/programs/{program_id}/delete", response_class=HTMLResponse)
def delete_confirm(request: Request, program_id: int, filter: str | None = None) -> HTMLResponse:
    preview = service.delete_preview(request.app.state.engine, program_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="programme not found")
    values = {"preview": preview, "current_filter": TrackerFilter.parse(filter)}
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
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="programme not found") from exc
    except (service.NotDropped, service.JobRunning) as exc:
        return PlainTextResponse(str(exc), status_code=409)
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


@router.post("/tracker/programs/{program_id}/{action}", response_model=None)
def act(
    request: Request,
    program_id: int,
    action: str,
    reason: Annotated[str, Form()] = "",
    filter: Annotated[str, Form()] = "",
) -> Response:
    try:
        tracker_action = TrackerAction(action)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="unknown action") from exc
    current = TrackerFilter.parse(filter)
    engine = request.app.state.engine
    try:
        updated = service.apply_action(engine, program_id, tracker_action, reason)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="programme not found") from exc
    except InvalidTransition as exc:
        return PlainTextResponse(str(exc), status_code=409)
    if not _is_htmx(request):
        return RedirectResponse(f"/tracker?filter={current.value}", status_code=303)
    values = {"card": updated, "tabs": service.tabs(engine), "current_filter": current}
    return templates.TemplateResponse(request, "_card_update.html", values)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"
