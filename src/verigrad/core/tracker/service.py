"""What the Tracker page calls: cards, status actions and permanent delete. Routes stay thin."""

from datetime import datetime
from urllib.parse import urlsplit

from pydantic import BaseModel
from sqlalchemy import Engine
from sqlmodel import Session

from verigrad.config import Settings
from verigrad.core.store import repository as repo
from verigrad.core.store.models import FetchOutcome, Program, ProgramStatus
from verigrad.core.tracker.files import remove_snapshot_folders
from verigrad.core.tracker.status import (
    TrackerAction,
    TrackerFilter,
    allowed_actions,
    drop_reason_for,
    next_status,
)

# Label per latest-snapshot outcome, in display order.
OUTCOME_LABELS = {
    FetchOutcome.SUCCESS: "saved",
    FetchOutcome.MANUAL_IMPORT: "uploaded",
    FetchOutcome.BLOCKED: "blocked",
    FetchOutcome.FAILED: "failed",
}
NOT_FETCHED = "not fetched"


class NotDropped(ValueError):
    """Permanent delete is only offered for DROPPED programmes."""


class JobRunning(ValueError):
    """A fetch job for this programme is still queued or running."""


class SourceLine(BaseModel):
    id: int
    url: str
    role: str
    label: str  # latest snapshot outcome (OUTCOME_LABELS) or NOT_FETCHED


class ProgramCard(BaseModel):
    id: int
    name: str
    url: str
    host: str
    university: str | None = None
    country: str | None = None  # filled by extraction (step 4); shown as "—" until then
    status: ProgramStatus
    status_changed_at: datetime
    drop_reason: str | None = None
    source_count: int = 0
    fetch_summary: dict[str, int] = {}
    sources: list[SourceLine] = []
    latest_job_id: int | None = None
    actions: list[TrackerAction] = []


class TabView(BaseModel):
    filter: TrackerFilter
    label: str
    count: int


class DeletePreview(BaseModel):
    card: ProgramCard
    footprint: repo.ProgramFootprint

    @property
    def folders_to_remove(self) -> list[str]:
        return [d for d in self.footprint.snapshot_dirs if d not in self.footprint.shared_dirs]


class DeleteResult(BaseModel):
    removed_dirs: list[str] = []
    kept_dirs: list[str] = []
    errors: list[str] = []


def list_cards(engine: Engine, tracker_filter: TrackerFilter) -> list[ProgramCard]:
    with Session(engine) as session:
        counts = repo.source_counts(session)
        programs = repo.list_programs(session, tracker_filter.statuses)
        return [_card(session, program, counts.get(_id(program), 0)) for program in programs]


def tabs(engine: Engine) -> list[TabView]:
    with Session(engine) as session:
        counts = repo.status_counts(session)
    return [
        TabView(filter=f, label=f.label, count=sum(counts.get(s, 0) for s in f.statuses))
        for f in TrackerFilter
    ]


def get_card(engine: Engine, program_id: int) -> ProgramCard | None:
    with Session(engine) as session:
        program = session.get(Program, program_id)
        if program is None:
            return None
        return _card(session, program, repo.source_counts(session).get(program_id, 0))


def apply_action(
    engine: Engine, program_id: int, action: TrackerAction, reason: str | None = None
) -> ProgramCard:
    """Raises LookupError (unknown programme) or InvalidTransition."""
    with Session(engine) as session:
        program = session.get(Program, program_id)
        if program is None:
            raise LookupError(f"programme {program_id} not found")
        status = next_status(program.status, action)
        drop_reason = (
            drop_reason_for(program.status, reason) if action == TrackerAction.DROP else None
        )
        repo.set_program_status(session, program_id, status, drop_reason)
    card = get_card(engine, program_id)
    assert card is not None
    return card


def delete_preview(engine: Engine, program_id: int) -> DeletePreview | None:
    with Session(engine) as session:
        program = session.get(Program, program_id)
        if program is None:
            return None
        card = _card(session, program, repo.source_counts(session).get(program_id, 0))
        return DeletePreview(card=card, footprint=repo.program_footprint(session, program_id))


def delete_program(engine: Engine, settings: Settings, program_id: int) -> DeleteResult:
    """Permanently delete a DROPPED programme: DB rows, then any snapshot folder no other
    programme uses. Raises LookupError, NotDropped or JobRunning."""
    with Session(engine) as session:
        program = session.get(Program, program_id)
        if program is None:
            raise LookupError(f"programme {program_id} not found")
        if program.status != ProgramStatus.DROPPED:
            raise NotDropped("drop the programme before deleting it permanently")
        if repo.has_active_job(session, program_id):
            raise JobRunning("a fetch job for this programme is still running")
        dirs = repo.delete_program_rows(session, program_id)
        unused = [d for d in dirs if not repo.snapshot_dir_in_use(session, d)]
    removed, errors = remove_snapshot_folders(settings.data_dir, unused)
    return DeleteResult(
        removed_dirs=removed, kept_dirs=[d for d in dirs if d not in unused], errors=errors
    )


def _card(session: Session, program: Program, source_count: int) -> ProgramCard:
    program_id = _id(program)
    latest = repo.latest_snapshot_per_source(session, program_id)
    summary: dict[str, int] = {}
    for outcome, label in OUTCOME_LABELS.items():
        n = sum(1 for s in latest.values() if s.fetch_outcome == outcome)
        if n:
            summary[label] = n
    if not_fetched := source_count - len(latest):
        summary[NOT_FETCHED] = not_fetched
    sources = [
        SourceLine(
            id=source.id,
            url=source.url,
            role=source.role.value,
            label=OUTCOME_LABELS[latest[source.id].fetch_outcome]
            if source.id in latest
            else NOT_FETCHED,
        )
        for source in repo.list_sources(session, program_id)
        if source.id is not None
    ]
    job = repo.latest_job_for_program(session, program_id)
    host = urlsplit(program.url).hostname or program.url
    return ProgramCard(
        id=program_id,
        name=program.name or host,
        url=program.url,
        host=host,
        university=program.university,
        status=program.status,
        status_changed_at=program.status_changed_at,
        drop_reason=program.drop_reason,
        source_count=source_count,
        fetch_summary=summary,
        sources=sources,
        latest_job_id=job.id if job else None,
        actions=allowed_actions(program.status),
    )


def _id(program: Program) -> int:
    assert program.id is not None
    return program.id
