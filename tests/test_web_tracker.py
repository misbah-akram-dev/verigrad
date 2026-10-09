"""Tracker page and HTMX actions via TestClient (no browser, no network)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session

from verigrad.config import Settings
from verigrad.core.store import repository as repo
from verigrad.core.store.models import (
    FetchOutcome,
    JobKind,
    Program,
    ProgramStatus,
    Snapshot,
    SourceRole,
)

HTMX = {"HX-Request": "true"}
SHARED = "https://admissions.uni.example/deadlines"


@pytest.fixture
def web(client: TestClient) -> TestClient:
    return client


@pytest.fixture
def db(web: TestClient) -> Engine:
    return web.app.state.engine  # type: ignore[attr-defined]


def seed(
    engine: Engine,
    url: str,
    status: ProgramStatus = ProgramStatus.SAVED,
    name: str | None = None,
    extra: list[tuple[str, SourceRole]] | None = None,
) -> int:
    with Session(engine) as s:
        program = repo.create_program_with_sources(
            s, name, [(url, SourceRole.PROGRAM), *(extra or [])]
        )
        assert program.id is not None
        if status != ProgramStatus.SAVED:
            repo.set_program_status(s, program.id, status, None)
        return program.id


def status_of(engine: Engine, program_id: int) -> ProgramStatus | None:
    with Session(engine) as s:
        program = s.get(Program, program_id)
        return program.status if program else None


def post(web: TestClient, program_id: int, action: str, **form: str):  # type: ignore[no-untyped-def]
    return web.post(f"/tracker/programs/{program_id}/{action}", data=form, headers=HTMX)


# --- page and filters --------------------------------------------------------------------


def test_default_view_shows_targeting_only(web: TestClient, db: Engine) -> None:
    targeting = seed(db, "https://t.example/", ProgramStatus.TARGETING, name="MSc Targeted")
    saved = seed(db, "https://s.example/", name="MSc Saved")
    html = web.get("/tracker").text
    assert f'id="program-{targeting}"' in html and "MSc Targeted" in html
    assert f'id="program-{saved}"' not in html
    assert 'data-filter="targeting"' in html and 'aria-current="true"' in html
    assert "Coming in v1 step" not in html  # no longer a placeholder


@pytest.mark.parametrize(
    ("filter_", "visible"),
    [
        ("saved", {ProgramStatus.SAVED}),
        ("applied", {ProgramStatus.APPLIED, ProgramStatus.ADMITTED, ProgramStatus.REJECTED}),
        ("dropped", {ProgramStatus.DROPPED}),
        ("all", set(ProgramStatus)),
        ("bogus", {ProgramStatus.TARGETING}),  # unknown → default
    ],
)
def test_filters(web: TestClient, db: Engine, filter_: str, visible: set[ProgramStatus]) -> None:
    ids = {s: seed(db, f"https://{s.value.lower()}.example/", s) for s in ProgramStatus}
    html = web.get(f"/tracker?filter={filter_}").text
    for status, program_id in ids.items():
        assert (f'id="program-{program_id}"' in html) == (status in visible), status


def test_tab_counts(web: TestClient, db: Engine) -> None:
    for status in ProgramStatus:
        seed(db, f"https://{status.value.lower()}.example/", status)
    html = web.get("/tracker?filter=all").text
    for filter_, count in [("targeting", 1), ("saved", 1), ("applied", 3), ("all", 6)]:
        tab = html.split(f'data-filter="{filter_}"', 1)[1].split("</a>", 1)[0]
        assert f'<span class="ml-0.5 text-xs text-slate-400" data-count>{count}</span>' in tab


def test_card_contents_and_placeholder_slot(web: TestClient, db: Engine) -> None:
    program_id = seed(db, "https://cs.uni.example/msc", ProgramStatus.TARGETING)
    with Session(db) as s:
        source_id = repo.list_sources(s, program_id)[0].id
        repo.add_snapshot(
            s,
            Snapshot(
                program_id=program_id,
                source_id=source_id,  # type: ignore[arg-type]
                url="https://cs.uni.example/msc",
                fetch_outcome=FetchOutcome.BLOCKED,
                snapshot_dir="snapshots/x",
            ),
        )
        job_id = repo.create_job(s, JobKind.FETCH, program_id).id
    html = web.get("/tracker").text
    assert "cs.uni.example" in html  # no name → host
    assert '<span data-field="university">—</span>' in html
    assert '<span data-field="country">—</span>' in html
    assert "1 source" in html and "1 blocked" in html
    assert f'href="/add/jobs/{job_id}"' in html
    assert 'data-slot="funding-eligibility"' in html
    assert "filled after extraction (step 4)" in html


def test_buttons_follow_the_status(web: TestClient, db: Engine) -> None:
    applied = seed(db, "https://a.example/", ProgramStatus.APPLIED)
    html = web.get("/tracker?filter=applied").text
    card = html.split(f'id="program-{applied}"', 1)[1].split("</article>", 1)[0]
    assert 'data-action="admit"' in card and 'data-action="reject"' in card
    assert "✕ Withdraw" in card and 'placeholder="withdrawn"' in card
    assert 'data-action="track"' not in card and 'data-action="delete"' not in card
    assert 'hx-confirm="Record the result as ADMITTED?"' in card


# --- HTMX actions ------------------------------------------------------------------------


def test_track_returns_card_partial_with_oob_tabs(web: TestClient, db: Engine) -> None:
    program_id = seed(db, "https://s.example/")
    response = post(web, program_id, "track", filter="saved")
    assert response.status_code == 200
    html = response.text
    assert "<html" not in html
    assert f'id="program-{program_id}"' in html and 'data-status="TARGETING"' in html
    assert 'id="tracker-tabs"' in html and 'hx-swap-oob="true"' in html
    assert "data-moved" in html  # left the Saved filter
    assert 'data-action="apply"' in html and 'data-action="track"' not in html
    assert status_of(db, program_id) == ProgramStatus.TARGETING


def test_full_lifecycle_through_the_web(web: TestClient, db: Engine) -> None:
    program_id = seed(db, "https://s.example/")
    steps = [
        ("track", ProgramStatus.TARGETING),
        ("apply", ProgramStatus.APPLIED),
        ("admit", ProgramStatus.ADMITTED),
        ("undo-result", ProgramStatus.APPLIED),
        ("reject", ProgramStatus.REJECTED),
        ("undo-result", ProgramStatus.APPLIED),
        ("drop", ProgramStatus.DROPPED),
        ("restore", ProgramStatus.TARGETING),
    ]
    for action, expected in steps:
        assert post(web, program_id, action, filter="all").status_code == 200, action
        assert status_of(db, program_id) == expected, action


def test_drop_with_reason_and_withdraw_default(web: TestClient, db: Engine) -> None:
    targeting = seed(db, "https://t.example/", ProgramStatus.TARGETING)
    html = post(web, targeting, "drop", reason="no scholarship", filter="targeting").text
    assert '<span data-field="drop-reason">no scholarship</span>' in html
    assert 'data-action="delete"' in html  # dropped: delete is offered

    applied = seed(db, "https://a.example/", ProgramStatus.APPLIED)
    html = post(web, applied, "drop", reason="", filter="applied").text
    assert '<span data-field="drop-reason">withdrawn</span>' in html


def test_invalid_transition_is_409(web: TestClient, db: Engine) -> None:
    program_id = seed(db, "https://s.example/")
    response = post(web, program_id, "admit")
    assert response.status_code == 409
    assert "can't admit a programme that is SAVED" in response.text
    assert status_of(db, program_id) == ProgramStatus.SAVED


def test_unknown_programme_or_action_is_404(web: TestClient, db: Engine) -> None:
    program_id = seed(db, "https://s.example/")
    assert post(web, program_id, "explode").status_code == 404
    assert post(web, 999, "track").status_code == 404
    assert web.get("/tracker/programs/999/card").status_code == 404
    assert web.get("/tracker/programs/999/delete").status_code == 404
    assert web.post("/tracker/programs/999/delete", headers=HTMX).status_code == 404


def test_without_htmx_actions_redirect_back(web: TestClient, db: Engine) -> None:
    program_id = seed(db, "https://s.example/")
    response = web.post(
        f"/tracker/programs/{program_id}/track",
        data={"filter": "saved"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/tracker?filter=saved"


# --- permanent delete --------------------------------------------------------------------


def _snapshot(engine: Engine, settings: Settings, program_id: int, index: int, **kw) -> Snapshot:  # type: ignore[no-untyped-def]
    with Session(engine) as s:
        source_id = repo.list_sources(s, program_id)[index].id
        folder = kw.pop("folder", f"snapshots/{program_id}/{source_id}/t")
        (settings.data_dir / folder).mkdir(parents=True, exist_ok=True)
        return repo.add_snapshot(
            s,
            Snapshot(
                program_id=program_id,
                source_id=source_id,  # type: ignore[arg-type]
                fetch_outcome=FetchOutcome.SUCCESS,
                snapshot_dir=folder,
                **kw,
            ),
        )


def test_delete_confirm_then_delete_with_a_shared_snapshot(
    web: TestClient, db: Engine, settings: Settings
) -> None:
    extra = [(SHARED, SourceRole.ADMISSIONS)]
    a = seed(db, "https://a.example/", ProgramStatus.DROPPED, name="MSc A", extra=extra)
    b = seed(db, "https://b.example/", ProgramStatus.TARGETING, extra=extra)
    own = _snapshot(db, settings, a, 0, url="https://a.example/")
    shared = _snapshot(db, settings, a, 1, url=SHARED)
    _snapshot(db, settings, b, 1, url=SHARED, folder=shared.snapshot_dir,
              reused_from_snapshot_id=shared.id)  # fmt: skip

    confirm = web.get(f"/tracker/programs/{a}/delete?filter=dropped", headers=HTMX).text
    assert "data-confirm-delete" in confirm and "Permanently delete “MSc A”?" in confirm
    assert "1 snapshot folder(s) removed from disk" in confirm
    assert "data-shared-folders" in confirm and shared.snapshot_dir in confirm

    cancel = web.get(f"/tracker/programs/{a}/card?filter=dropped", headers=HTMX).text
    assert f'id="program-{a}"' in cancel and "data-confirm-delete" not in cancel

    response = web.post(f"/tracker/programs/{a}/delete", data={"filter": "dropped"}, headers=HTMX)
    assert response.status_code == 200
    assert "data-deleted" in response.text and "1 shared folder(s) kept" in response.text
    assert 'hx-swap-oob="true"' in response.text
    assert status_of(db, a) is None
    assert not (settings.data_dir / own.snapshot_dir).exists()
    assert (settings.data_dir / shared.snapshot_dir).is_dir()
    assert status_of(db, b) == ProgramStatus.TARGETING


def test_delete_refused_unless_dropped(web: TestClient, db: Engine) -> None:
    program_id = seed(db, "https://t.example/", ProgramStatus.TARGETING)
    response = web.post(f"/tracker/programs/{program_id}/delete", headers=HTMX)
    assert response.status_code == 409
    assert "drop the programme before deleting it" in response.text
    assert status_of(db, program_id) == ProgramStatus.TARGETING


def test_delete_refused_while_a_job_runs(web: TestClient, db: Engine) -> None:
    program_id = seed(db, "https://d.example/", ProgramStatus.DROPPED)
    with Session(db) as s:
        repo.create_job(s, JobKind.FETCH, program_id)  # queued, never submitted
    response = web.post(f"/tracker/programs/{program_id}/delete", headers=HTMX)
    assert response.status_code == 409
    assert status_of(db, program_id) == ProgramStatus.DROPPED
