"""Tracker service + repository: status changes, cards, filters and permanent delete."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from verigrad.config import Settings
from verigrad.core.store import repository as repo
from verigrad.core.store.models import (
    Extraction,
    FetchOutcome,
    Job,
    JobKind,
    JobStatus,
    LLMCall,
    Program,
    ProgramSource,
    ProgramStatus,
    Snapshot,
    SourceRole,
    Task,
)
from verigrad.core.tracker import service
from verigrad.core.tracker.files import remove_snapshot_folders
from verigrad.core.tracker.status import InvalidTransition, TrackerAction, TrackerFilter

SHARED = "https://admissions.uni.example/deadlines"


# --- seeding helpers ---------------------------------------------------------------------


def make_programme(
    engine: Engine,
    url: str,
    status: ProgramStatus = ProgramStatus.SAVED,
    extra: list[tuple[str, SourceRole]] | None = None,
) -> tuple[int, list[int]]:
    """(program_id, source_ids)."""
    with Session(engine) as s:
        program = repo.create_program_with_sources(
            s, None, [(url, SourceRole.PROGRAM), *(extra or [])]
        )
        assert program.id is not None
        if status != ProgramStatus.SAVED:
            repo.set_program_status(s, program.id, status, None)
        return program.id, [src.id for src in repo.list_sources(s, program.id)]  # type: ignore[misc]


def make_snapshot(
    engine: Engine,
    settings: Settings,
    program_id: int,
    source_id: int,
    outcome: FetchOutcome = FetchOutcome.SUCCESS,
    url: str = "https://uni.example/",
    reuse_of: int | None = None,
) -> Snapshot:
    """An original snapshot with a real folder, or a reused row pointing at `reuse_of`'s."""
    with Session(engine) as s:
        if reuse_of is not None:
            original = s.get(Snapshot, reuse_of)
            assert original is not None
            folder, url, outcome = original.snapshot_dir, original.url, original.fetch_outcome
        else:
            folder = f"snapshots/{program_id}/{source_id}/t{source_id}"
            (settings.data_dir / folder).mkdir(parents=True, exist_ok=True)
            (settings.data_dir / folder / "text.txt").write_text("page", encoding="utf-8")
        return repo.add_snapshot(
            s,
            Snapshot(
                program_id=program_id,
                source_id=source_id,
                url=url,
                fetch_outcome=outcome,
                snapshot_dir=folder,
                reused_from_snapshot_id=reuse_of,
            ),
        )


def drop(engine: Engine, program_id: int) -> None:
    with Session(engine) as s:
        repo.set_program_status(s, program_id, ProgramStatus.DROPPED, None)


def exists(settings: Settings, snapshot: Snapshot) -> bool:
    return (settings.data_dir / snapshot.snapshot_dir).is_dir()


# --- status changes ----------------------------------------------------------------------


def test_every_status_change_records_status_changed_at(engine: Engine) -> None:
    program_id, _ = make_programme(engine, "https://uni.example/a")
    t0 = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    with Session(engine) as s:
        for i, status in enumerate([ProgramStatus.TARGETING, ProgramStatus.APPLIED]):
            stamp = t0 + timedelta(minutes=i)
            program = repo.set_program_status(s, program_id, status, None, now=lambda t=stamp: t)
            assert program.status == status
            assert program.status_changed_at.replace(tzinfo=UTC) == stamp


def test_apply_action_walks_the_lifecycle(engine: Engine) -> None:
    program_id, _ = make_programme(engine, "https://uni.example/a")
    before = service.get_card(engine, program_id)
    assert before is not None
    steps = [
        (TrackerAction.TRACK, ProgramStatus.TARGETING),
        (TrackerAction.APPLY, ProgramStatus.APPLIED),
        (TrackerAction.ADMIT, ProgramStatus.ADMITTED),
        (TrackerAction.UNDO_RESULT, ProgramStatus.APPLIED),
        (TrackerAction.REJECT, ProgramStatus.REJECTED),
        (TrackerAction.UNDO_RESULT, ProgramStatus.APPLIED),
        (TrackerAction.DROP, ProgramStatus.DROPPED),
        (TrackerAction.RESTORE, ProgramStatus.TARGETING),
    ]
    last = before.status_changed_at
    for action, expected in steps:
        card = service.apply_action(engine, program_id, action)
        assert card.status == expected
        assert card.status_changed_at >= last
        last = card.status_changed_at


def test_drop_reasons(engine: Engine) -> None:
    program_id, _ = make_programme(engine, "https://uni.example/a", ProgramStatus.TARGETING)
    card = service.apply_action(engine, program_id, TrackerAction.DROP, "  no funding  ")
    assert card.drop_reason == "no funding"
    card = service.apply_action(engine, program_id, TrackerAction.RESTORE)
    assert card.drop_reason is None  # restore clears it

    service.apply_action(engine, program_id, TrackerAction.APPLY)
    card = service.apply_action(engine, program_id, TrackerAction.DROP, "")
    assert card.drop_reason == "withdrawn"


def test_invalid_action_and_unknown_programme(engine: Engine) -> None:
    program_id, _ = make_programme(engine, "https://uni.example/a")
    with pytest.raises(InvalidTransition):
        service.apply_action(engine, program_id, TrackerAction.ADMIT)
    with Session(engine) as s:
        assert s.get(Program, program_id).status == ProgramStatus.SAVED  # type: ignore[union-attr]
    with pytest.raises(LookupError):
        service.apply_action(engine, 999, TrackerAction.TRACK)


# --- cards and filters -------------------------------------------------------------------


def test_filters_and_tab_counts(engine: Engine) -> None:
    made = {
        status: make_programme(engine, f"https://uni.example/{status.value}", status)[0]
        for status in ProgramStatus
    }

    def ids(f: TrackerFilter) -> set[int]:
        return {card.id for card in service.list_cards(engine, f)}

    assert ids(TrackerFilter.TARGETING) == {made[ProgramStatus.TARGETING]}
    assert ids(TrackerFilter.SAVED) == {made[ProgramStatus.SAVED]}
    assert ids(TrackerFilter.APPLIED) == {
        made[ProgramStatus.APPLIED],
        made[ProgramStatus.ADMITTED],
        made[ProgramStatus.REJECTED],
    }
    assert ids(TrackerFilter.DROPPED) == {made[ProgramStatus.DROPPED]}
    assert ids(TrackerFilter.ALL) == set(made.values())
    counts = {tab.filter: tab.count for tab in service.tabs(engine)}
    assert counts == {
        TrackerFilter.TARGETING: 1,
        TrackerFilter.SAVED: 1,
        TrackerFilter.APPLIED: 3,
        TrackerFilter.DROPPED: 1,
        TrackerFilter.ALL: 6,
    }


def test_card_fields_and_fetch_summary(engine: Engine, settings: Settings) -> None:
    other_id, other_sources = make_programme(
        engine, "https://other.example/", extra=[(SHARED, SourceRole.ADMISSIONS)]
    )
    original = make_snapshot(engine, settings, other_id, other_sources[1], url=SHARED)

    program_id, sources = make_programme(
        engine,
        "https://cs.uni.example/msc?x=1",
        extra=[
            (SHARED, SourceRole.ADMISSIONS),
            ("https://uni.example/fees", SourceRole.FEES),
            ("https://uni.example/funding", SourceRole.SCHOLARSHIP),
        ],
    )
    # program page: blocked first, then uploaded → only the latest counts
    make_snapshot(engine, settings, program_id, sources[0], FetchOutcome.BLOCKED)
    make_snapshot(engine, settings, program_id, sources[0], FetchOutcome.MANUAL_IMPORT)
    make_snapshot(engine, settings, program_id, sources[1], reuse_of=original.id)  # reused
    make_snapshot(engine, settings, program_id, sources[2], FetchOutcome.FAILED)
    # sources[3] never fetched
    with Session(engine) as s:
        job = repo.create_job(s, JobKind.FETCH, program_id)

    card = service.get_card(engine, program_id)
    assert card is not None
    assert card.name == "cs.uni.example" and card.host == "cs.uni.example"  # no name → host
    assert card.university is None and card.country is None  # step 4 fills these
    assert card.source_count == 4
    assert card.fetch_summary == {"saved": 1, "uploaded": 1, "failed": 1, "not fetched": 1}
    assert card.latest_job_id == job.id
    assert card.actions == [TrackerAction.TRACK, TrackerAction.DROP]


# --- permanent delete --------------------------------------------------------------------


def test_delete_removes_rows_and_folder_but_keeps_cost_rows(
    engine: Engine, settings: Settings
) -> None:
    program_id, sources = make_programme(engine, "https://uni.example/a")
    snapshot = make_snapshot(engine, settings, program_id, sources[0])
    with Session(engine) as s:
        job = repo.create_job(s, JobKind.EXTRACT, program_id)
        job_id = job.id
        s.add(
            Extraction(
                snapshot_id=snapshot.id,  # type: ignore[arg-type]
                field_path="program_name",
                value_json='"MSc"',
                confidence="high",
                model="m",
                prompt_version="v1",
            )
        )
        s.add(
            Task(
                program_id=program_id,
                title="Ask recommenders",
                due_date_pkt=datetime(2026, 12, 1, tzinfo=UTC),
                lead_time_days=21,
            )
        )
        s.add(_llm_call(program_id=program_id, job_id=job_id))
        s.commit()
        repo.update_job(s, job_id, status=JobStatus.SUCCEEDED)  # type: ignore[arg-type]
    drop(engine, program_id)

    preview = service.delete_preview(engine, program_id)
    assert preview is not None
    footprint = preview.footprint
    assert (footprint.sources, footprint.snapshots, footprint.extractions) == (1, 1, 1)
    assert (footprint.tasks, footprint.jobs, footprint.llm_calls) == (1, 1, 1)
    assert preview.folders_to_remove == [snapshot.snapshot_dir]

    result = service.delete_program(engine, settings, program_id)
    assert result.removed_dirs == [snapshot.snapshot_dir] and not result.errors
    assert not exists(settings, snapshot)
    assert not (settings.data_dir / "snapshots" / str(program_id)).exists()  # parents pruned
    with Session(engine) as s:
        for table in (Program, ProgramSource, Snapshot, Extraction, Task, Job):
            assert s.exec(select(table)).all() == [], table
        (call,) = s.exec(select(LLMCall)).all()
        assert call.program_id is None and call.job_id is None and call.cost_usd == 0.01


def test_delete_promotes_a_reusing_programme_and_keeps_the_shared_folder(
    engine: Engine, settings: Settings
) -> None:
    a_id, a_sources = make_programme(
        engine, "https://a.example/", extra=[(SHARED, SourceRole.ADMISSIONS)]
    )
    b_id, b_sources = make_programme(
        engine, "https://b.example/", extra=[(SHARED, SourceRole.ADMISSIONS)]
    )
    c_id, c_sources = make_programme(
        engine, "https://c.example/", extra=[(SHARED, SourceRole.ADMISSIONS)]
    )
    a_own = make_snapshot(engine, settings, a_id, a_sources[0], url="https://a.example/")
    shared = make_snapshot(engine, settings, a_id, a_sources[1], url=SHARED)
    b_reuse = make_snapshot(engine, settings, b_id, b_sources[1], reuse_of=shared.id)
    c_reuse = make_snapshot(engine, settings, c_id, c_sources[1], reuse_of=shared.id)
    with Session(engine) as s:
        stats_before = repo.fetch_stats(s)
    drop(engine, a_id)

    preview = service.delete_preview(engine, a_id)
    assert preview is not None
    assert preview.footprint.shared_dirs == [shared.snapshot_dir]
    assert preview.folders_to_remove == [a_own.snapshot_dir]

    result = service.delete_program(engine, settings, a_id)
    assert result.removed_dirs == [a_own.snapshot_dir]
    assert result.kept_dirs == [shared.snapshot_dir]
    assert exists(settings, shared) and not exists(settings, a_own)
    with Session(engine) as s:
        b_row, c_row = s.get(Snapshot, b_reuse.id), s.get(Snapshot, c_reuse.id)
        assert b_row is not None and c_row is not None
        assert b_row.reused_from_snapshot_id is None  # oldest reuser promoted to original
        assert c_row.reused_from_snapshot_id == b_row.id
        assert repo.reusable_snapshot_for_url(s, SHARED).id == b_row.id  # type: ignore[union-attr]
        stats_after = repo.fetch_stats(s)
    # one SUCCESS attempt removed (A's own page) and the shared one handed over
    assert stats_after.success_rate == stats_before.success_rate

    # deleting the remaining users removes the folder at last
    drop(engine, b_id)
    service.delete_program(engine, settings, b_id)
    assert exists(settings, shared)  # C still uses it
    drop(engine, c_id)
    service.delete_program(engine, settings, c_id)
    assert not exists(settings, shared)


def test_delete_keeps_a_folder_owned_by_another_programme(
    engine: Engine, settings: Settings
) -> None:
    owner_id, owner_sources = make_programme(
        engine, "https://owner.example/", extra=[(SHARED, SourceRole.ADMISSIONS)]
    )
    shared = make_snapshot(engine, settings, owner_id, owner_sources[1], url=SHARED)
    user_id, user_sources = make_programme(
        engine, "https://user.example/", extra=[(SHARED, SourceRole.ADMISSIONS)]
    )
    make_snapshot(engine, settings, user_id, user_sources[1], reuse_of=shared.id)
    drop(engine, user_id)

    result = service.delete_program(engine, settings, user_id)
    assert result.removed_dirs == [] and result.kept_dirs == [shared.snapshot_dir]
    assert exists(settings, shared)
    with Session(engine) as s:
        owner_row = s.get(Snapshot, shared.id)
        assert owner_row is not None and owner_row.reused_from_snapshot_id is None


def test_delete_is_refused_unless_dropped_and_idle(engine: Engine, settings: Settings) -> None:
    program_id, _ = make_programme(engine, "https://uni.example/a", ProgramStatus.TARGETING)
    with pytest.raises(service.NotDropped):
        service.delete_program(engine, settings, program_id)

    drop(engine, program_id)
    with Session(engine) as s:
        job = repo.create_job(s, JobKind.FETCH, program_id)  # queued
    with pytest.raises(service.JobRunning):
        service.delete_program(engine, settings, program_id)

    with Session(engine) as s:
        repo.update_job(s, job.id, status=JobStatus.BLOCKED)  # type: ignore[arg-type]
    service.delete_program(engine, settings, program_id)
    with pytest.raises(LookupError):
        service.delete_program(engine, settings, program_id)


def test_folder_removal_never_leaves_the_snapshots_folder(settings: Settings) -> None:
    outside = settings.data_dir / "keep"
    outside.mkdir()
    (settings.data_dir / "snapshots").mkdir()
    removed, errors = remove_snapshot_folders(
        settings.data_dir, ["keep", "snapshots", "snapshots/../keep", "snapshots/9/9/missing"]
    )
    assert outside.is_dir() and (settings.data_dir / "snapshots").is_dir()
    assert removed == ["snapshots/9/9/missing"]  # already gone: nothing to do
    assert len(errors) == 3


def _llm_call(program_id: int, job_id: int | None) -> LLMCall:
    return LLMCall(
        purpose="extract",
        model="claude-sonnet-5-5",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.01,
        estimated_cost_usd=0.01,
        latency_ms=100,
        job_id=job_id,
        program_id=program_id,
    )
