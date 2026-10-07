"""Repository functions. Callers pass a SQLModel `Session`; no other module writes SQL."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, col, select

from verigrad.core.store.models import (
    FetchOutcome,
    Job,
    JobKind,
    JobStatus,
    LLMCall,
    Program,
    ProgramSource,
    Snapshot,
    SourceRole,
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
