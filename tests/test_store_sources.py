import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from verigrad.core.store import repository as repo
from verigrad.core.store.models import (
    FetchOutcome,
    Job,
    JobKind,
    JobStatus,
    ProgramStatus,
    Snapshot,
    SourceRole,
)

ADMISSIONS = "https://admissions.uni.example/timelines"


@pytest.fixture
def ids(engine: Engine) -> tuple[int, int]:
    """(program_id, source_id) of a programme with one admissions source."""
    with Session(engine) as s:
        program = repo.create_program_with_sources(s, None, [(ADMISSIONS, SourceRole.ADMISSIONS)])
        assert program.id is not None
        source_id = repo.list_sources(s, program.id)[0].id
        assert source_id is not None
        return program.id, source_id


def _add(s: Session, ids: tuple[int, int], outcome: FetchOutcome, **extra: object) -> Snapshot:
    program_id, source_id = ids
    return repo.add_snapshot(
        s,
        Snapshot(
            program_id=program_id,
            source_id=source_id,
            url=ADMISSIONS,
            fetch_outcome=outcome,
            snapshot_dir="snapshots/x",
            **extra,
        ),
    )


def test_program_url_is_the_program_role_url(engine: Engine) -> None:
    with Session(engine) as s:
        program = repo.create_program_with_sources(
            s,
            "MS CS",
            [(ADMISSIONS, SourceRole.ADMISSIONS), ("https://cs.uni.example/", SourceRole.PROGRAM)],
        )
        assert program.id is not None
        assert program.url == "https://cs.uni.example/"
        assert program.status == ProgramStatus.SAVED
        roles = [x.role for x in repo.list_sources(s, program.id)]
        assert roles == [SourceRole.ADMISSIONS, SourceRole.PROGRAM]


def test_program_url_falls_back_to_first_url(engine: Engine) -> None:
    with Session(engine) as s:
        program = repo.create_program_with_sources(s, " ", [(ADMISSIONS, SourceRole.ADMISSIONS)])
        assert program.url == ADMISSIONS
        assert program.name is None


def test_needs_a_source(engine: Engine) -> None:
    with Session(engine) as s, pytest.raises(ValueError):
        repo.create_program_with_sources(s, "x", [])


def test_only_program_role_identifies_a_duplicate(engine: Engine) -> None:
    with Session(engine) as s:
        sources = [("https://a.example/", SourceRole.PROGRAM), (ADMISSIONS, SourceRole.ADMISSIONS)]
        first = repo.create_program_with_sources(s, "A", sources)
        found = repo.find_program_by_program_url(s, "https://a.example/")
        assert found is not None and found.id == first.id
        assert repo.find_program_by_program_url(s, ADMISSIONS) is None


def test_reusable_snapshot_ignores_failures_and_reused_rows(
    engine: Engine, ids: tuple[int, int]
) -> None:
    with Session(engine) as s:
        assert repo.reusable_snapshot_for_url(s, ADMISSIONS) is None
        _add(s, ids, FetchOutcome.BLOCKED)
        assert repo.reusable_snapshot_for_url(s, ADMISSIONS) is None
        ok = _add(s, ids, FetchOutcome.SUCCESS)
        _add(s, ids, FetchOutcome.SUCCESS, reused_from_snapshot_id=ok.id)
        found = repo.reusable_snapshot_for_url(s, ADMISSIONS)
        assert found is not None and found.id == ok.id


def test_manual_import_is_reusable(engine: Engine, ids: tuple[int, int]) -> None:
    with Session(engine) as s:
        imported = _add(s, ids, FetchOutcome.MANUAL_IMPORT, imported_manually=True)
        found = repo.reusable_snapshot_for_url(s, ADMISSIONS)
        assert found is not None and found.id == imported.id


def test_latest_snapshot_per_source(engine: Engine, ids: tuple[int, int]) -> None:
    with Session(engine) as s:
        _add(s, ids, FetchOutcome.BLOCKED)
        newest = _add(s, ids, FetchOutcome.SUCCESS)
        assert repo.latest_snapshot_per_source(s, ids[0])[ids[1]].id == newest.id


def test_fetch_stats_count_only_automatic_attempts(engine: Engine, ids: tuple[int, int]) -> None:
    with Session(engine) as s:
        ok = _add(s, ids, FetchOutcome.SUCCESS)
        _add(s, ids, FetchOutcome.SUCCESS)
        _add(s, ids, FetchOutcome.BLOCKED)
        _add(s, ids, FetchOutcome.FAILED)
        _add(s, ids, FetchOutcome.MANUAL_IMPORT, imported_manually=True)
        _add(s, ids, FetchOutcome.SUCCESS, reused_from_snapshot_id=ok.id)
        stats = repo.fetch_stats(s)
    assert (stats.success, stats.blocked, stats.failed, stats.manual_imports) == (2, 1, 1, 1)
    assert stats.attempts == 4
    assert stats.success_rate == 0.5


def test_fetch_stats_empty(engine: Engine) -> None:
    with Session(engine) as s:
        assert repo.fetch_stats(s).success_rate is None


def test_fail_interrupted_jobs(engine: Engine) -> None:
    with Session(engine) as s:
        queued = repo.create_job(s, JobKind.FETCH, None)
        running = repo.create_job(s, JobKind.FETCH, None)
        done = repo.create_job(s, JobKind.FETCH, None)
        assert queued.id and running.id and done.id
        repo.update_job(s, running.id, status=JobStatus.RUNNING)
        repo.update_job(s, done.id, status=JobStatus.SUCCEEDED)

        assert repo.fail_interrupted_jobs(s) == 2

        for job_id in (queued.id, running.id):
            job = s.get(Job, job_id)
            assert job and job.status == JobStatus.FAILED and job.error and job.finished_at
        finished = s.get(Job, done.id)
        assert finished and finished.status == JobStatus.SUCCEEDED


def test_update_unknown_job(engine: Engine) -> None:
    with Session(engine) as s, pytest.raises(LookupError):
        repo.update_job(s, 999)
