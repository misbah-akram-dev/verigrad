"""Fetch job: snapshot every source of one programme (or one source, for a re-fetch).

Fetch once, reuse (D8): a source whose URL already has a SUCCESS or MANUAL_IMPORT snapshot
gets a row pointing at that folder instead of a new fetch; only a forced re-fetch fetches again.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from playwright.async_api import Browser, async_playwright
from sqlalchemy import Engine
from sqlmodel import Session

from verigrad.config import Settings
from verigrad.core.fetch.models import SnapshotFiles, SnapshotMeta, SnapshotResult
from verigrad.core.fetch.polite import DomainThrottle, RobotsChecker
from verigrad.core.fetch.snapshot import (
    Politeness,
    launch_browser,
    robots_fetcher,
    snapshot_source,
    write_meta,
)
from verigrad.core.jobs.models import JobProgress, SourceProgress, SourceState
from verigrad.core.jobs.runner import save_progress
from verigrad.core.store import repository as repo
from verigrad.core.store.models import FetchOutcome, JobStatus, ProgramSource, Snapshot

log = logging.getLogger(__name__)

_STATE_FOR_OUTCOME = {
    FetchOutcome.SUCCESS: SourceState.SAVED,
    FetchOutcome.BLOCKED: SourceState.BLOCKED,
    FetchOutcome.FAILED: SourceState.FAILED,
    FetchOutcome.MANUAL_IMPORT: SourceState.IMPORTED,
}


async def run_fetch_job(
    engine: Engine,
    settings: Settings,
    throttle: DomainThrottle,
    job_id: int,
    program_id: int,
    source_ids: list[int] | None = None,
    force: bool = False,
) -> JobStatus:
    with Session(engine) as session:
        sources = [
            s
            for s in repo.list_sources(session, program_id)
            if source_ids is None or s.id in source_ids
        ]
    progress = JobProgress(
        sources=[SourceProgress(source_id=_id(s), url=s.url, role=s.role) for s in sources]
    )
    save_progress(engine, job_id, progress)

    async with async_playwright() as pw:
        api = await pw.request.new_context()
        politeness = Politeness(
            RobotsChecker(robots_fetcher(api, settings.fetch_timeout_seconds)), throttle
        )
        browser: Browser | None = None
        try:
            for source, item in zip(sources, progress.sources, strict=True):
                if not force and _reuse(engine, source, item):
                    save_progress(engine, job_id, progress)
                    continue
                item.state = SourceState.FETCHING
                save_progress(engine, job_id, progress)
                browser = browser or await launch_browser(pw, settings.browser_channel)
                result = await _snapshot(browser, settings, source, politeness)
                snapshot = _record(engine, settings, source, result)
                item.state = _STATE_FOR_OUTCOME[snapshot.fetch_outcome]
                item.reason, item.snapshot_id = snapshot.outcome_reason, snapshot.id
                save_progress(engine, job_id, progress)
        finally:
            if browser is not None:
                await browser.close()
            await api.dispose()
    return overall_status(progress)


def overall_status(progress: JobProgress) -> JobStatus:
    states = {item.state for item in progress.sources}
    if SourceState.FAILED in states:
        return JobStatus.FAILED
    if SourceState.BLOCKED in states:
        return JobStatus.BLOCKED
    return JobStatus.SUCCEEDED


def new_snapshot_folder(data_dir: Path, program_id: int, source_id: int) -> Path:
    base = data_dir / "snapshots" / str(program_id) / str(source_id)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder, n = base / stamp, 1
    while folder.exists():
        n += 1
        folder = base / f"{stamp}-{n}"
    return folder


def snapshot_row(settings: Settings, source: ProgramSource, result: SnapshotResult) -> Snapshot:
    meta, files = result.meta, result.files
    return Snapshot(
        program_id=source.program_id,
        source_id=_id(source),
        fetched_at=meta.fetched_at,
        fetch_outcome=meta.outcome,
        outcome_reason=meta.reason,
        url=meta.url,
        final_url=meta.final_url,
        http_status=meta.http_status,
        snapshot_dir=result.folder.relative_to(settings.data_dir).as_posix(),
        html_path=files.html,
        text_path=files.text,
        visible_text_path=files.visible_text,
        screenshot_path=files.screenshot,
        meta_path=files.meta,
        json_paths=json.dumps([f.path for f in meta.json_files]),
        pdf_paths=json.dumps([f.path for f in meta.pdf_files]),
        content_hash=meta.content_hash,
        imported_manually=meta.imported_manually,
    )


def _reuse(engine: Engine, source: ProgramSource, item: SourceProgress) -> bool:
    with Session(engine) as session:
        original = repo.reusable_snapshot_for_url(session, source.url)
        if original is None:
            return False
        copy = Snapshot.model_validate(
            original.model_dump(exclude={"id", "program_id", "source_id"})
            | {"program_id": source.program_id, "source_id": source.id}
        )
        copy.reused_from_snapshot_id = original.id
        copy = repo.add_snapshot(session, copy)
        item.state, item.snapshot_id = SourceState.REUSED, copy.id
        item.reason = f"reused snapshot {original.id}"
    log.info("reused snapshot %s for %s", original.id, source.url)
    return True


async def _snapshot(
    browser: Browser, settings: Settings, source: ProgramSource, politeness: Politeness
) -> SnapshotResult:
    folder = new_snapshot_folder(settings.data_dir, source.program_id, _id(source))
    try:
        return await snapshot_source(
            browser,
            source.url,
            folder,
            politeness,
            settings.fetch_timeout_seconds,
            channel=settings.browser_channel,
        )
    except Exception as exc:  # one bad page must not stop the other sources
        log.exception("snapshot crashed for %s", source.url)
        folder.mkdir(parents=True, exist_ok=True)
        meta = SnapshotMeta(
            url=source.url, outcome=FetchOutcome.FAILED, reason="error", error=str(exc)[:300]
        )
        write_meta(folder, meta)
        return SnapshotResult(folder=folder, meta=meta, files=SnapshotFiles())


def _record(
    engine: Engine, settings: Settings, source: ProgramSource, result: SnapshotResult
) -> Snapshot:
    with Session(engine) as session:
        return repo.add_snapshot(session, snapshot_row(settings, source, result))


def _id(source: ProgramSource) -> int:
    assert source.id is not None
    return source.id
