"""Repository functions. Callers pass a SQLModel `Session`; no other module writes SQL."""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import delete, func, update
from sqlmodel import Session, col, select

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
    utcnow,
)

REUSABLE_OUTCOMES = (FetchOutcome.SUCCESS, FetchOutcome.MANUAL_IMPORT)


def record_llm_call(session: Session, call: LLMCall) -> LLMCall:
    session.add(call)
    session.commit()
    session.refresh(call)
    return call


def job_spend(session: Session, job_id: int) -> Decimal:
    """Total actual spend (USD) of every logged Claude call for one job."""
    total = session.exec(
        select(func.coalesce(func.sum(LLMCall.cost_usd), 0.0)).where(LLMCall.job_id == job_id)
    ).one()
    return Decimal(str(total))


# --- programmes and sources -------------------------------------------------------------


def create_program_with_sources(
    session: Session, name: str | None, sources: list[tuple[str, SourceRole]]
) -> Program:
    """Create a SAVED programme. `programs.url` is the program-role URL, else the first URL."""
    if not sources:
        raise ValueError("a programme needs at least one source URL")
    primary = next((url for url, role in sources if role == SourceRole.PROGRAM), sources[0][0])
    program = Program(url=primary, name=(name or "").strip() or None)
    session.add(program)
    session.flush()
    assert program.id is not None
    for url, role in sources:
        session.add(ProgramSource(program_id=program.id, url=url, role=role))
    session.commit()
    session.refresh(program)
    return program


def find_program_by_program_url(session: Session, url: str) -> Program | None:
    """Only a program-role URL identifies a programme; shared admissions pages don't."""
    return session.exec(
        select(Program)
        .join(ProgramSource, col(ProgramSource.program_id) == col(Program.id))
        .where(ProgramSource.url == url, ProgramSource.role == SourceRole.PROGRAM)
    ).first()


def list_sources(session: Session, program_id: int) -> list[ProgramSource]:
    return list(
        session.exec(
            select(ProgramSource)
            .where(ProgramSource.program_id == program_id)
            .order_by(col(ProgramSource.id))
        )
    )


# --- snapshots --------------------------------------------------------------------------


def add_snapshot(session: Session, snapshot: Snapshot) -> Snapshot:
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return snapshot


def reusable_snapshot_for_url(session: Session, url: str) -> Snapshot | None:
    """Newest original (not reused) SUCCESS or MANUAL_IMPORT snapshot of this exact URL."""
    return session.exec(
        select(Snapshot)
        .where(
            Snapshot.url == url,
            col(Snapshot.fetch_outcome).in_(REUSABLE_OUTCOMES),
            col(Snapshot.reused_from_snapshot_id).is_(None),
        )
        .order_by(col(Snapshot.fetched_at).desc(), col(Snapshot.id).desc())
    ).first()


def latest_snapshot_per_source(session: Session, program_id: int) -> dict[int, Snapshot]:
    rows = session.exec(
        select(Snapshot)
        .where(Snapshot.program_id == program_id)
        .order_by(col(Snapshot.fetched_at), col(Snapshot.id))
    )
    latest: dict[int, Snapshot] = {}
    for snapshot in rows:
        latest[snapshot.source_id] = snapshot
    return latest


class FetchStats(BaseModel):
    """Automatic fetch attempts only: manual imports and reused rows are not attempts."""

    success: int = 0
    blocked: int = 0
    failed: int = 0
    manual_imports: int = 0

    @property
    def attempts(self) -> int:
        return self.success + self.blocked + self.failed

    @property
    def success_rate(self) -> float | None:
        return self.success / self.attempts if self.attempts else None


def fetch_stats(session: Session) -> FetchStats:
    rows = session.exec(
        select(Snapshot.fetch_outcome, func.count())
        .where(col(Snapshot.reused_from_snapshot_id).is_(None))
        .group_by(col(Snapshot.fetch_outcome))
    ).all()
    counts = {FetchOutcome(outcome): n for outcome, n in rows}
    return FetchStats(
        success=counts.get(FetchOutcome.SUCCESS, 0),
        blocked=counts.get(FetchOutcome.BLOCKED, 0),
        failed=counts.get(FetchOutcome.FAILED, 0),
        manual_imports=counts.get(FetchOutcome.MANUAL_IMPORT, 0),
    )


# --- jobs -------------------------------------------------------------------------------


def latest_job_for_program(session: Session, program_id: int) -> Job | None:
    return session.exec(
        select(Job).where(Job.program_id == program_id).order_by(col(Job.id).desc())
    ).first()


def create_job(session: Session, kind: JobKind, program_id: int | None) -> Job:
    job = Job(kind=kind, program_id=program_id)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def update_job(
    session: Session,
    job_id: int,
    *,
    status: JobStatus | None = None,
    progress: str | None = None,
    error: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise LookupError(f"job {job_id} not found")
    if status is not None:
        job.status = status
    if progress is not None:
        job.progress = progress
    if error is not None:
        job.error = error
    if started_at is not None:
        job.started_at = started_at
    if finished_at is not None:
        job.finished_at = finished_at
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def fail_interrupted_jobs(session: Session) -> int:
    """Jobs left queued/running by a previous app process can never finish; mark them failed."""
    jobs = session.exec(
        select(Job).where(col(Job.status).in_((JobStatus.QUEUED, JobStatus.RUNNING)))
    ).all()
    for job in jobs:
        job.status = JobStatus.FAILED
        job.error = "interrupted (app restarted)"
        job.finished_at = utcnow()
        session.add(job)
    session.commit()
    return len(jobs)


# --- tracker: status and listing ---------------------------------------------------------


def set_program_status(
    session: Session,
    program_id: int,
    status: ProgramStatus,
    drop_reason: str | None,
    now: Callable[[], datetime] = utcnow,
) -> Program:
    """Every status change records `status_changed_at`. Rules live in core/tracker/status.py."""
    program = session.get(Program, program_id)
    if program is None:
        raise LookupError(f"programme {program_id} not found")
    program.status = status
    program.drop_reason = drop_reason
    program.status_changed_at = now()
    session.add(program)
    session.commit()
    session.refresh(program)
    return program


def list_programs(
    session: Session, statuses: tuple[ProgramStatus, ...] | None = None
) -> list[Program]:
    query = select(Program).order_by(col(Program.status_changed_at).desc(), col(Program.id).desc())
    if statuses is not None:
        query = query.where(col(Program.status).in_(statuses))
    return list(session.exec(query))


def status_counts(session: Session) -> dict[ProgramStatus, int]:
    rows = session.exec(select(Program.status, func.count()).group_by(col(Program.status))).all()
    return {ProgramStatus(status): n for status, n in rows}


def source_counts(session: Session) -> dict[int, int]:
    rows = session.exec(
        select(ProgramSource.program_id, func.count()).group_by(col(ProgramSource.program_id))
    ).all()
    return dict(rows)


def has_active_job(session: Session, program_id: int) -> bool:
    return (
        session.exec(
            select(Job.id).where(
                Job.program_id == program_id,
                col(Job.status).in_((JobStatus.QUEUED, JobStatus.RUNNING)),
            )
        ).first()
        is not None
    )


# --- tracker: permanent delete -----------------------------------------------------------


class ProgramFootprint(BaseModel):
    """What a permanent delete touches. `shared_dirs` are snapshot folders that rows of other
    programmes also point at; they are kept."""

    sources: int = 0
    snapshots: int = 0
    extractions: int = 0
    tasks: int = 0
    jobs: int = 0
    llm_calls: int = 0
    snapshot_dirs: list[str] = []
    shared_dirs: list[str] = []


def program_footprint(session: Session, program_id: int) -> ProgramFootprint:
    snapshots = session.exec(select(Snapshot).where(Snapshot.program_id == program_id)).all()
    snapshot_ids = [s.id for s in snapshots]
    job_ids = list(session.exec(select(Job.id).where(Job.program_id == program_id)))
    dirs = sorted({s.snapshot_dir for s in snapshots})
    return ProgramFootprint(
        sources=_count(session, ProgramSource, col(ProgramSource.program_id) == program_id),
        snapshots=len(snapshots),
        extractions=_count(session, Extraction, col(Extraction.snapshot_id).in_(snapshot_ids)),
        tasks=_count(session, Task, col(Task.program_id) == program_id),
        jobs=len(job_ids),
        llm_calls=_count(
            session,
            LLMCall,
            (col(LLMCall.program_id) == program_id) | col(LLMCall.job_id).in_(job_ids),
        ),
        snapshot_dirs=dirs,
        shared_dirs=[
            d for d in dirs if snapshot_dir_in_use(session, d, exclude_program=program_id)
        ],
    )


def snapshot_dir_in_use(
    session: Session, snapshot_dir: str, exclude_program: int | None = None
) -> bool:
    """Does any snapshot row (optionally: of another programme) point at this folder?"""
    query = select(Snapshot.id).where(Snapshot.snapshot_dir == snapshot_dir)
    if exclude_program is not None:
        query = query.where(Snapshot.program_id != exclude_program)
    return session.exec(query).first() is not None


def delete_program_rows(session: Session, program_id: int) -> list[str]:
    """Delete a programme and everything that belongs to it, in one transaction.

    - An original snapshot reused by another programme: the oldest reusing row is promoted to
      original and the other reusers point at it, so the shared folder stays owned.
    - `llm_calls` are kept (the spend happened) with `program_id`/`job_id` cleared.
    Returns the programme's snapshot folders; the caller removes the ones no row uses any more.
    """
    if session.get(Program, program_id) is None:
        raise LookupError(f"programme {program_id} not found")
    snapshots = session.exec(select(Snapshot).where(Snapshot.program_id == program_id)).all()
    snapshot_ids = [s.id for s in snapshots]
    job_ids = list(session.exec(select(Job.id).where(Job.program_id == program_id)))

    for original in snapshots:
        reusers = session.exec(
            select(Snapshot)
            .where(Snapshot.reused_from_snapshot_id == original.id)
            .where(Snapshot.program_id != program_id)
            .order_by(col(Snapshot.id))
        ).all()
        if not reusers:
            continue
        promoted, others = reusers[0], reusers[1:]
        promoted.reused_from_snapshot_id = None
        session.add(promoted)
        for other in others:
            other.reused_from_snapshot_id = promoted.id
            session.add(other)
    session.flush()

    session.exec(
        update(Snapshot)
        .where(col(Snapshot.program_id) == program_id)
        .values(reused_from_snapshot_id=None)
    )
    session.exec(
        update(LLMCall)
        .where((col(LLMCall.program_id) == program_id) | col(LLMCall.job_id).in_(job_ids))
        .values(program_id=None, job_id=None)
    )
    session.exec(delete(Extraction).where(col(Extraction.snapshot_id).in_(snapshot_ids)))
    session.exec(delete(Task).where(col(Task.program_id) == program_id))
    session.exec(delete(Snapshot).where(col(Snapshot.program_id) == program_id))
    session.exec(delete(Job).where(col(Job.program_id) == program_id))
    session.exec(delete(ProgramSource).where(col(ProgramSource.program_id) == program_id))
    session.exec(delete(Program).where(col(Program.id) == program_id))
    session.commit()
    return sorted({s.snapshot_dir for s in snapshots})


def _count(session: Session, table: type, condition: object) -> int:
    return session.exec(select(func.count()).select_from(table).where(condition)).one()
