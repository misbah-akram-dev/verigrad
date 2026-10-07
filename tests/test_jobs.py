"""Job runner (no browser) and the fetch job end to end (browser, local fixture site)."""

import asyncio
import sys
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from fixture_site import FixtureSite
from verigrad.config import Settings
from verigrad.core.fetch.service import new_snapshot_folder, run_fetch_job
from verigrad.core.jobs.models import JobProgress, SourceState
from verigrad.core.jobs.runner import JobRunner
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
def runner(engine: Engine, settings: Settings):  # type: ignore[no-untyped-def]
    job_runner = JobRunner(engine, settings)
    yield job_runner
    job_runner.shutdown()


def _new_job(engine: Engine, program_id: int | None = None) -> int:
    with Session(engine) as session:
        job_id = repo.create_job(session, JobKind.FETCH, program_id).id
    assert job_id is not None
    return job_id


def _job(engine: Engine, job_id: int) -> Job:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        assert job is not None
        return job


# --- runner ------------------------------------------------------------------------------


def test_runner_runs_work_on_its_own_loop(engine: Engine, runner: JobRunner) -> None:
    seen: dict[str, object] = {}

    async def work() -> JobStatus:
        seen["loop"] = type(asyncio.get_running_loop()).__name__
        return JobStatus.SUCCEEDED

    job_id = _new_job(engine)
    runner.submit(job_id, work).result(timeout=10)
    job = _job(engine, job_id)
    assert job.status == JobStatus.SUCCEEDED
    assert job.started_at and job.finished_at
    if sys.platform == "win32":  # Playwright needs a loop that can start subprocesses
        assert seen["loop"] == "ProactorEventLoop"


def test_runner_records_a_crash(engine: Engine, runner: JobRunner) -> None:
    async def work() -> JobStatus:
        raise RuntimeError("boom")

    job_id = _new_job(engine)
    runner.submit(job_id, work).result(timeout=10)
    job = _job(engine, job_id)
    assert job.status == JobStatus.FAILED
    assert job.error == "RuntimeError: boom"


def test_snapshot_folders_never_collide(tmp_path: Path) -> None:
    first = new_snapshot_folder(tmp_path, 1, 2)
    first.mkdir(parents=True)
    second = new_snapshot_folder(tmp_path, 1, 2)
    assert first != second and second.parent == first.parent


# --- fetch job (browser) -----------------------------------------------------------------


def _program(engine: Engine, sources: list[tuple[str, SourceRole]]) -> int:
    with Session(engine) as session:
        program_id = repo.create_program_with_sources(session, None, sources).id
    assert program_id is not None
    return program_id


def _fetch(
    engine: Engine, runner: JobRunner, program_id: int, **kwargs: object
) -> tuple[Job, JobProgress]:
    job_id = _new_job(engine, program_id)

    def work():  # type: ignore[no-untyped-def]
        return run_fetch_job(
            runner.engine, runner.settings, runner.throttle, job_id, program_id, **kwargs
        )

    runner.submit(job_id, work).result(timeout=120)
    job = _job(engine, job_id)
    return job, JobProgress.parse(job.progress)


@pytest.mark.browser
@pytest.mark.usefixtures("chromium")
def test_fetch_job_snapshots_every_source(
    engine: Engine, runner: JobRunner, settings: Settings, site: FixtureSite
) -> None:
    program_id = _program(
        engine,
        [
            (site.url("normal.html"), SourceRole.PROGRAM),
            (site.url("challenge.html"), SourceRole.ADMISSIONS),
        ],
    )
    job, progress = _fetch(engine, runner, program_id)

    assert job.status == JobStatus.BLOCKED
    assert [(p.state, p.reason) for p in progress.sources] == [
        (SourceState.SAVED, None),
        (SourceState.BLOCKED, "challenge_page"),
    ]
    with Session(engine) as session:
        rows = session.exec(select(Snapshot).order_by(Snapshot.id)).all()  # type: ignore[arg-type]
    assert [r.fetch_outcome for r in rows] == [FetchOutcome.SUCCESS, FetchOutcome.BLOCKED]
    ok = rows[0]
    folder = settings.data_dir / ok.snapshot_dir
    assert ok.snapshot_dir.startswith(f"snapshots/{program_id}/{ok.source_id}/")
    assert (folder / str(ok.text_path)).exists() and (folder / str(ok.meta_path)).exists()
    assert ok.content_hash and ok.http_status == 200


@pytest.mark.browser
@pytest.mark.usefixtures("chromium")
def test_shared_admissions_url_is_reused_not_refetched(
    engine: Engine, runner: JobRunner, site: FixtureSite
) -> None:
    shared = site.url("json.html")
    first = _program(
        engine, [(site.url("normal.html"), SourceRole.PROGRAM), (shared, SourceRole.ADMISSIONS)]
    )
    second = _program(
        engine, [(site.url("hidden.html"), SourceRole.PROGRAM), (shared, SourceRole.ADMISSIONS)]
    )
    _fetch(engine, runner, first)
    hits_before = site.hits["/json.html"]

    job, progress = _fetch(engine, runner, second)

    assert job.status == JobStatus.SUCCEEDED
    assert site.hits["/json.html"] == hits_before  # not fetched again
    assert [p.state for p in progress.sources] == [SourceState.SAVED, SourceState.REUSED]
    with Session(engine) as session:
        reused = session.get(Snapshot, progress.sources[1].snapshot_id)
        assert reused is not None and reused.reused_from_snapshot_id is not None
        original = session.get(Snapshot, reused.reused_from_snapshot_id)
        assert original is not None
        assert reused.snapshot_dir == original.snapshot_dir
        assert reused.program_id == second and original.program_id == first
        assert repo.fetch_stats(session).attempts == 3  # the reused row isn't an attempt


@pytest.mark.browser
@pytest.mark.usefixtures("chromium")
def test_forced_refetch_adds_a_new_snapshot_and_keeps_history(
    engine: Engine, runner: JobRunner, site: FixtureSite
) -> None:
    program_id = _program(engine, [(site.url("normal.html"), SourceRole.PROGRAM)])
    _, first = _fetch(engine, runner, program_id)
    source_id = first.sources[0].source_id
    hits_before = site.hits["/normal.html"]

    _, again = _fetch(engine, runner, program_id)  # not forced → reused
    assert again.sources[0].state == SourceState.REUSED
    job, forced = _fetch(engine, runner, program_id, source_ids=[source_id], force=True)

    assert job.status == JobStatus.SUCCEEDED
    assert forced.sources[0].state == SourceState.SAVED
    assert site.hits["/normal.html"] == hits_before + 1
    with Session(engine) as session:
        rows = session.exec(select(Snapshot).where(Snapshot.source_id == source_id)).all()
        latest = repo.latest_snapshot_per_source(session, program_id)[source_id]
    assert len(rows) == 3
    assert len({r.snapshot_dir for r in rows}) == 2  # original folder + the re-fetch folder
    assert latest.id == forced.sources[0].snapshot_id
