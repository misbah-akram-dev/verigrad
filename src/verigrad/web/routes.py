"""Page routes. Thin: render templates; all logic lives in core/."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

router = APIRouter()

NAV_PAGES: list[dict[str, str | int]] = [
    {"path": "/add", "label": "Add", "step": 2, "blurb": "Paste a programme URL to snapshot it."},
    {"path": "/tracker", "label": "Tracker", "step": 7, "blurb": "Your shortlist and statuses."},
    {
        "path": "/review",
        "label": "Review",
        "step": 7,
        "blurb": "Check and confirm doubtful fields.",
    },
    {"path": "/plan", "label": "Plan", "step": 8, "blurb": "Start-by dates in PKT and .ics."},
    {"path": "/dashboard", "label": "Dashboard", "step": 6, "blurb": "Accuracy and calibration."},
    {"path": "/costs", "label": "Costs", "step": 6, "blurb": "Spend by programme and purpose."},
]


def _context(request: Request, active: str) -> dict[str, object]:
    return {"nav_pages": NAV_PAGES, "active": active, "settings": request.app.state.settings}


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "home.html", _context(request, "/"))


def _make_placeholder(page: dict[str, str | int]):  # type: ignore[no-untyped-def]
    def placeholder(request: Request) -> HTMLResponse:
        context = _context(request, str(page["path"])) | {"page": page}
        return templates.TemplateResponse(request, "placeholder.html", context)

    return placeholder


for _page in NAV_PAGES:
    router.add_api_route(
        str(_page["path"]),
        _make_placeholder(_page),
        methods=["GET"],
        response_class=HTMLResponse,
        name=str(_page["label"]).lower(),
    )
