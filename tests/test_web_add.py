"""Add page flow via TestClient: form → background fetch job → polling panel → files."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from fixture_site import APOSTROPHE_PATH, FixtureSite
from helpers import job_id_from_redirect, wait_for_job
from helpers import submit_add_form as submit
from verigrad.config import Settings
from verigrad.core.jobs.models import JobProgress, SourceState
from verigrad.core.store import repository as repo
from verigrad.core.store.models import (
    FetchOutcome,
    Job,
    JobKind,
    JobStatus,
    Snapshot,
    SourceRole,
)


@pytest.fixture
def web(client: TestClient) -> TestClient:
    return client


# --- form (no browser) -------------------------------------------------------------------


def test_add_page_has_form_with_roles(web: TestClient) -> None:
    html = web.get("/add").text
    assert 'action="/add"' in html and 'name="url"' in html
    for role in ("program", "admissions", "scholarship", "fees", "other"):
        assert f'value="{role}"' in html
    assert 'hx-get="/add/source-row"' in html


def test_source_row_partial(web: TestClient) -> None:
    html = web.get("/add/source-row").text
    assert 'name="url"' in html and '<option value="admissions" selected>' in html


@pytest.mark.parametrize(
    ("urls", "message"),
    [
        (["ftp://uni.example/file"], "Not a valid http(s) URL"),
        (["not a url"], "Not a valid http(s) URL"),
        ([""], "Add at least one URL."),
    ],
)
def test_invalid_submissions_rerender_the_form(
    web: TestClient, urls: list[str], message: str
) -> None:
    response = web.post("/add", data={"url": urls, "role": ["program"] * len(urls)})
    assert response.status_code == 422
    assert message in response.text
    assert 'action="/add"' in response.text


def test_duplicate_program_url_links_to_existing(web: TestClient) -> None:
    engine = web.app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        existing = repo.create_program_with_sources(
            session, "A", [("https://cs.uni.example/", SourceRole.PROGRAM)]
        )
        program_id = existing.id
        job_id = repo.create_job(session, JobKind.FETCH, program_id).id
    response = web.post("/add", data={"url": ["https://CS.uni.example"], "role": ["program"]})
    assert response.status_code == 409
    assert f"already added as programme #{program_id}" in response.text
    assert f'href="/add/jobs/{job_id}"' in response.text


def test_unknown_job_and_source_are_404(web: TestClient) -> None:
    assert web.get("/add/jobs/999").status_code == 404
    assert web.get("/add/jobs/999/panel").status_code == 404
    assert web.post("/sources/999/refetch", follow_redirects=False).status_code == 404


def test_snapshot_files_are_served_safely(web: TestClient, settings: Settings) -> None:
    engine = web.app.state.engine  # type: ignore[attr-defined]
    folder = settings.data_dir / "snapshots" / "1" / "1" / "t"
    folder.mkdir(parents=True)
    (folder / "page.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    (folder / "text.txt").write_text("deadline", encoding="utf-8")
    (settings.data_dir / "secret.txt").write_text("outside", encoding="utf-8")
    with Session(engine) as session:
        program = repo.create_program_with_sources(
            session, None, [("https://u.example/", SourceRole.PROGRAM)]
        )
        source_id = repo.list_sources(session, program.id)[0].id  # type: ignore[arg-type]
        snapshot = repo.add_snapshot(
            session,
            Snapshot(
                program_id=program.id,  # type: ignore[arg-type]
                source_id=source_id,  # type: ignore[arg-type]
                url="https://u.example/",
                fetch_outcome=FetchOutcome.SUCCESS,
                snapshot_dir="snapshots/1/1/t",
            ),
        )
    base = f"/snapshots/{snapshot.id}/files"

    html = web.get(f"{base}/page.html")
    assert html.status_code == 200
    assert html.headers["content-type"].startswith("text/plain")  # never rendered as HTML
    assert html.headers["content-security-policy"] == "sandbox"
    assert web.get(f"{base}/text.txt").text == "deadline"
    assert web.get(f"{base}/../../../../secret.txt").status_code == 404
    assert web.get(f"{base}/%2E%2E/%2E%2E/%2E%2E/%2E%2E/secret.txt").status_code == 404
    assert web.get(f"{base}/missing.txt").status_code == 404
    assert web.get("/snapshots/999/files/text.txt").status_code == 404


# --- full flow (browser, local fixture site) ---------------------------------------------


@pytest.mark.browser
@pytest.mark.usefixtures("chromium")
def test_add_fetches_sources_and_panel_shows_results(web: TestClient, site: FixtureSite) -> None:
    job_id = submit(
        web,
        [(site.url("normal.html"), "program"), (site.url("challenge.html"), "admissions")],
        name="MSc Example",
    )
    page = web.get(f"/add/jobs/{job_id}").text
    assert "MSc Example" in page and 'id="job-panel"' in page

    job = wait_for_job(web, job_id)
    assert job.status == JobStatus.BLOCKED

    panel = web.get(f"/add/jobs/{job_id}/panel").text
    assert "hx-trigger" not in panel  # finished: polling stops
    assert 'data-state="saved"' in panel and 'data-state="blocked"' in panel
    assert "challenge_page" in panel
    assert "screenshot.png" in panel and ">Visible text</a>" in panel
    assert "Re-fetch" in panel


@pytest.mark.browser
@pytest.mark.usefixtures("chromium")
def test_two_programmes_share_one_admissions_url(web: TestClient, site: FixtureSite) -> None:
    shared = site.url("json.html")
    first = submit(web, [(site.url("normal.html"), "program"), (shared, "admissions")])
    wait_for_job(web, first)
    hits = site.hits["/json.html"]

    second = submit(web, [(site.url("hidden.html"), "program"), (shared, "admissions")])
    assert wait_for_job(web, second).status == JobStatus.SUCCEEDED

    assert site.hits["/json.html"] == hits
    panel = web.get(f"/add/jobs/{second}/panel").text
    assert 'data-state="reused"' in panel


@pytest.mark.browser
@pytest.mark.usefixtures("chromium")
def test_refetch_creates_a_new_snapshot(web: TestClient, site: FixtureSite) -> None:
    job_id = submit(web, [(site.url("normal.html"), "program")])
    wait_for_job(web, job_id)
    engine = web.app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        program_id = session.get(Job, job_id).program_id  # type: ignore[union-attr]
        source_id = repo.list_sources(session, program_id)[0].id  # type: ignore[arg-type]

    response = web.post(f"/sources/{source_id}/refetch", follow_redirects=False)
    assert response.status_code == 303
    refetch_job = int(response.headers["location"].rsplit("/", 1)[-1])
    assert wait_for_job(web, refetch_job).status == JobStatus.SUCCEEDED

    with Session(engine) as session:
        rows = session.exec(select(Snapshot).where(Snapshot.source_id == source_id)).all()
    assert len(rows) == 2


def _add_source(web: TestClient, program_id: int, url: str, role: str = "admissions") -> int:
    response = web.post(
        f"/tracker/programs/{program_id}/sources",
        data={"url": url, "role": role},
        follow_redirects=False,
    )
    return job_id_from_redirect(response)


def _program_of(web: TestClient, job_id: int) -> int:
    with Session(web.app.state.engine) as session:  # type: ignore[attr-defined]
        program_id = session.get(Job, job_id).program_id  # type: ignore[union-attr]
    assert program_id is not None
    return program_id


@pytest.mark.browser
@pytest.mark.usefixtures("chromium")
def test_add_source_fetches_only_it_and_reuses_a_shared_snapshot(
    web: TestClient, site: FixtureSite
) -> None:
    shared = site.url("json.html")
    wait_for_job(web, submit(web, [(site.url("normal.html"), "program"), (shared, "admissions")]))
    first_b = submit(web, [(site.url("hidden.html"), "program")])
    wait_for_job(web, first_b)
    program_b = _program_of(web, first_b)
    hits = site.hits.copy()

    job_id = _add_source(web, program_b, shared)
    assert wait_for_job(web, job_id).status == JobStatus.SUCCEEDED

    assert site.hits == hits  # nothing fetched: the shared page was reused
    panel = web.get(f"/add/jobs/{job_id}/panel").text
    assert panel.count("data-state=") == 1 and 'data-state="reused"' in panel
    with Session(web.app.state.engine) as session:  # type: ignore[attr-defined]
        assert len(repo.list_sources(session, program_b)) == 2
        rows = session.exec(select(Snapshot).where(Snapshot.program_id == program_b)).all()
    assert len(rows) == 2  # the earlier snapshot of hidden.html is untouched


@pytest.mark.browser
@pytest.mark.usefixtures("chromium")
def test_add_source_with_an_apostrophe_in_the_url(
    web: TestClient, site: FixtureSite, settings: Settings
) -> None:
    first = submit(web, [(site.url("normal.html"), "program")])
    wait_for_job(web, first)
    url = site.url(APOSTROPHE_PATH)

    job_id = _add_source(web, _program_of(web, first), url)
    assert wait_for_job(web, job_id).status == JobStatus.SUCCEEDED

    assert site.hits[APOSTROPHE_PATH] == 1
    panel = web.get(f"/add/jobs/{job_id}/panel").text
    assert 'data-state="saved"' in panel
    with Session(web.app.state.engine) as session:  # type: ignore[attr-defined]
        snapshot = session.exec(select(Snapshot).where(Snapshot.url == url)).one()
    assert snapshot.fetch_outcome == FetchOutcome.SUCCESS
    assert snapshot.visible_text_path is not None
    text = settings.data_dir / snapshot.snapshot_dir / snapshot.visible_text_path
    assert "APOSTROPHE_MARKER" in text.read_text(encoding="utf-8")


@pytest.mark.browser
@pytest.mark.usefixtures("chromium")
def test_refetch_all_fetches_every_source_again_and_keeps_history(
    web: TestClient, site: FixtureSite
) -> None:
    first = submit(
        web, [(site.url("normal.html"), "program"), (site.url("json.html"), "admissions")]
    )
    wait_for_job(web, first)
    program_id = _program_of(web, first)
    hits = site.hits.copy()

    response = web.post(f"/tracker/programs/{program_id}/refetch", follow_redirects=False)
    job_id = job_id_from_redirect(response)
    job = wait_for_job(web, job_id)
    assert job.status == JobStatus.SUCCEEDED

    engine = web.app.state.engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        source_ids = [s.id for s in repo.list_sources(session, program_id)]
        rows = session.exec(select(Snapshot).where(Snapshot.program_id == program_id)).all()
    progress = JobProgress.parse(job.progress).sources
    assert [item.source_id for item in progress] == source_ids  # one job, every source
    assert {item.state for item in progress} == {SourceState.SAVED}  # forced: not reused
    for path in ("/normal.html", "/json.html"):
        assert site.hits[path] == hits[path] + 1
    for source_id in source_ids:  # history kept: old + new snapshot, different folders
        dirs = {r.snapshot_dir for r in rows if r.source_id == source_id}
        assert len(dirs) == 2
