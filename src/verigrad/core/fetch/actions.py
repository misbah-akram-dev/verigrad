"""What the web layer calls: add a programme, re-fetch a source, build the job view, and
resolve snapshot files safely. Routes stay thin; logic lives here."""

import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel
from sqlalchemy import Engine
from sqlmodel import Session

from verigrad.config import Settings
from verigrad.core.fetch.manual_import import run_import_job, stage_upload
from verigrad.core.fetch.models import META, SnapshotMeta
from verigrad.core.fetch.service import run_fetch_job
from verigrad.core.jobs.models import JobProgress, SourceState
from verigrad.core.jobs.runner import JobRunner
from verigrad.core.store import repository as repo
from verigrad.core.store.models import (
    FetchOutcome,
    Job,
    JobKind,
    JobStatus,
    Program,
    ProgramSource,
    Snapshot,
    SourceRole,
)

MAX_SOURCES = 10


class SourceInput(BaseModel):
    url: str
    role: SourceRole


class AddRequest(BaseModel):
    name: str | None = None
    sources: list[SourceInput] = []


class AddOutcome(BaseModel):
    job_id: int | None = None
    errors: list[str] = []
    duplicate_program_id: int | None = None
    duplicate_job_id: int | None = None


def normalise_url(raw: str) -> str | None:
    """http(s) URL with a host, lower-case scheme/host, no fragment; None if invalid."""
    parts = urlsplit(raw.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    netloc = parts.netloc.lower()
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))


def parse_add_form(
    name: str | None, urls: list[str], roles: list[str]
) -> tuple[AddRequest, list[str]]:
    errors: list[str] = []
    sources: list[SourceInput] = []
    seen: set[str] = set()
    for raw, role in zip(urls, roles, strict=False):
        if not raw.strip():
            continue
        url = normalise_url(raw)
        if url is None:
            errors.append(f"Not a valid http(s) URL: {raw.strip()}")
            continue
        if role not in SourceRole._value2member_map_:
            errors.append(f"Unknown role for {url}: {role}")
            continue
        if url in seen:
            continue
        seen.add(url)
        sources.append(SourceInput(url=url, role=SourceRole(role)))
    if not sources and not errors:
        errors.append("Add at least one URL.")
    if len(sources) > MAX_SOURCES:
        errors.append(f"At most {MAX_SOURCES} URLs per programme.")
    return AddRequest(name=(name or "").strip() or None, sources=sources), errors


def add_programme(engine: Engine, runner: JobRunner, request: AddRequest) -> AddOutcome:
    """Create a SAVED programme + sources and start its fetch job.

    Only a program-role URL identifies a duplicate programme; admissions/scholarship/fees
    pages may be shared (their snapshots are reused by the fetch job).
    """
    with Session(engine) as session:
        for source in request.sources:
            if source.role != SourceRole.PROGRAM:
                continue
            existing = repo.find_program_by_program_url(session, source.url)
            if existing is not None and existing.id is not None:
                job = repo.latest_job_for_program(session, existing.id)
                return AddOutcome(
                    errors=[f"{source.url} is already added as programme #{existing.id}."],
                    duplicate_program_id=existing.id,
                    duplicate_job_id=job.id if job else None,
                )
        program = repo.create_program_with_sources(
            session, request.name, [(s.url, s.role) for s in request.sources]
        )
        assert program.id is not None
        job_id = _start_fetch(engine, runner, session, program.id)
    return AddOutcome(job_id=job_id)


def refetch_source(engine: Engine, runner: JobRunner, source_id: int) -> int | None:
    """Fetch one source again (new snapshot; history kept). None if the source doesn't exist."""
    with Session(engine) as session:
        source = session.get(ProgramSource, source_id)
        if source is None:
            return None
        return _start_fetch(engine, runner, session, source.program_id, [source_id], force=True)


def import_upload(
    engine: Engine, runner: JobRunner, source_id: int, filename: str, data: bytes
) -> int:
    """Stage an uploaded page/PDF for a source and start its import job. Raises UploadError
    (shown to the user) or LookupError (unknown source)."""
    with Session(engine) as session:
        source = session.get(ProgramSource, source_id)
        if source is None:
            raise LookupError(f"source {source_id} not found")
        staged = stage_upload(runner.settings, source, filename, data)
        job_id = repo.create_job(session, JobKind.FETCH, source.program_id).id
    assert job_id is not None

    def work():  # type: ignore[no-untyped-def]
        return run_import_job(engine, runner.settings, job_id, source_id, staged)

    runner.submit(job_id, work)
    return job_id


def latest_job_for_source(engine: Engine, source_id: int) -> int | None:
    with Session(engine) as session:
        source = session.get(ProgramSource, source_id)
        if source is None:
            return None
        job = repo.latest_job_for_program(session, source.program_id)
        return job.id if job else None


def _start_fetch(
    engine: Engine,
    runner: JobRunner,
    session: Session,
    program_id: int,
    source_ids: list[int] | None = None,
    force: bool = False,
) -> int:
    job_id = repo.create_job(session, JobKind.FETCH, program_id).id
    assert job_id is not None

    def work():  # type: ignore[no-untyped-def]
        return run_fetch_job(
            engine, runner.settings, runner.throttle, job_id, program_id, source_ids, force
        )

    runner.submit(job_id, work)
    return job_id


# --- job view for the polling panel -------------------------------------------------------


class FileLink(BaseModel):
    label: str
    path: str


class SourceView(BaseModel):
    source_id: int
    url: str
    role: str
    state: SourceState
    reason: str | None = None
    snapshot_id: int | None = None
    outcome: FetchOutcome | None = None
    reused_from: int | None = None
    imported: bool = False
    screenshot: bool = False
    files: list[FileLink] = []
    html_kb: int = 0
    visible_chars: int = 0
    json_count: int = 0
    pdf_count: int = 0
    skipped_pdfs: int = 0
    details_opened: int = 0
    toggles_clicked: int = 0
    navigated_away: list[str] = []
    error: str | None = None

    @property
    def can_upload(self) -> bool:
        return self.state in (SourceState.BLOCKED, SourceState.FAILED)


class JobView(BaseModel):
    job_id: int
    program_id: int | None
    program_name: str | None
    status: JobStatus
    error: str | None
    sources: list[SourceView]

    @property
    def running(self) -> bool:
        return self.status in (JobStatus.QUEUED, JobStatus.RUNNING)


def job_view(engine: Engine, settings: Settings, job_id: int) -> JobView | None:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            return None
        program = session.get(Program, job.program_id) if job.program_id else None
        views = []
        for item in JobProgress.parse(job.progress).sources:
            snapshot = session.get(Snapshot, item.snapshot_id) if item.snapshot_id else None
            views.append(_source_view(settings, item.model_dump(), snapshot))
        return JobView(
            job_id=job_id,
            program_id=job.program_id,
            program_name=program.name if program else None,
            status=job.status,
            error=job.error,
            sources=views,
        )


def _source_view(
    settings: Settings, item: dict[str, object], snapshot: Snapshot | None
) -> SourceView:
    view = SourceView.model_validate(item)
    if snapshot is None:
        return view
    view.outcome = snapshot.fetch_outcome
    view.reused_from = snapshot.reused_from_snapshot_id
    view.imported = snapshot.imported_manually
    view.screenshot = snapshot.screenshot_path is not None
    candidates = [
        ("Text", snapshot.text_path),
        ("Visible text", snapshot.visible_text_path),
        ("HTML (as text)", snapshot.html_path),
        ("meta.json", snapshot.meta_path),
    ]
    view.files = [FileLink(label=label, path=path) for label, path in candidates if path]
    view.files += [FileLink(label=p, path=p) for p in json.loads(snapshot.json_paths)]
    view.files += [FileLink(label=p, path=p) for p in json.loads(snapshot.pdf_paths)]
    meta = _load_meta(settings, snapshot)
    if meta is not None:
        view.html_kb = round(meta.html_bytes / 1024)
        view.visible_chars = meta.visible_text_chars
        view.json_count, view.pdf_count = len(meta.json_files), len(meta.pdf_files)
        view.skipped_pdfs = len(meta.skipped_pdfs)
        view.details_opened = meta.prep.details_opened
        view.toggles_clicked = meta.prep.toggles_clicked
        view.navigated_away = meta.prep.navigated_away
        view.error = meta.error
    return view


def _load_meta(settings: Settings, snapshot: Snapshot) -> SnapshotMeta | None:
    path = settings.data_dir / snapshot.snapshot_dir / (snapshot.meta_path or META)
    try:
        return SnapshotMeta.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- snapshot files -----------------------------------------------------------------------


def snapshot_file(
    engine: Engine, settings: Settings, snapshot_id: int, relative: str
) -> Path | None:
    """The file inside this snapshot's folder, or None. Rejects anything outside the folder."""
    with Session(engine) as session:
        snapshot = session.get(Snapshot, snapshot_id)
    if snapshot is None:
        return None
    folder = (settings.data_dir / snapshot.snapshot_dir).resolve()
    target = (folder / relative).resolve()
    if not target.is_relative_to(folder) or not target.is_file():
        return None
    return target
