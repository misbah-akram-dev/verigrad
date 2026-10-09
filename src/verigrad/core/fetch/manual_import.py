"""Manual import (spec §3.4, D8): a page saved from the user's own browser becomes a normal
snapshot with `imported_manually = true`.

HTML is rendered offline — JavaScript off, every network request aborted — to produce
visible_text.txt and a screenshot like a fetched page. Without the page's external CSS, some
styled-hidden text may count as visible. PDFs are stored as they are.
"""

import hashlib
import logging
import re
from pathlib import Path
from typing import Literal

from playwright.async_api import Browser, Route, async_playwright
from playwright.async_api import Error as PlaywrightError
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlmodel import Session

from verigrad.config import Settings
from verigrad.core.fetch.models import (
    PAGE_HTML,
    PDF_DIR,
    SCREENSHOT,
    TEXT,
    VISIBLE_TEXT,
    SavedFile,
    SnapshotFiles,
    SnapshotMeta,
    SnapshotResult,
)
from verigrad.core.fetch.prepare import OPEN_DETAILS_JS
from verigrad.core.fetch.service import new_snapshot_folder, snapshot_row
from verigrad.core.fetch.snapshot import browser_info, launch_browser, write_meta
from verigrad.core.fetch.text import content_hash, html_to_text, normalise_lines, page_title
from verigrad.core.jobs.models import JobProgress, SourceProgress, SourceState
from verigrad.core.jobs.runner import save_progress
from verigrad.core.store import repository as repo
from verigrad.core.store.models import FetchOutcome, JobStatus, ProgramSource

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
RENDER_TIMEOUT_MS = 15_000
_CHARSET = re.compile(rb"""charset\s*=\s*["']?([A-Za-z0-9_\-]+)""", re.IGNORECASE)


class UploadError(ValueError):
    """An upload we refuse; the message is shown to the user."""


class StagedUpload(BaseModel):
    folder: Path
    kind: Literal["html", "pdf"]
    filename: str
    relative_path: str
    bytes: int


def stage_upload(
    settings: Settings, source: ProgramSource, filename: str, data: bytes
) -> StagedUpload:
    """Validate an upload and write it into a new snapshot folder. Server-chosen file names."""
    if not data:
        raise UploadError("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError(f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf":
        if not data.startswith(b"%PDF"):
            raise UploadError("That file is not a valid PDF.")
        kind: Literal["html", "pdf"] = "pdf"
        relative = f"{PDF_DIR}/01_upload.pdf"
        payload = data
    elif suffix in (".html", ".htm"):
        kind, relative = "html", PAGE_HTML
        payload = decode_html(data).encode("utf-8")
    else:
        raise UploadError("Upload a saved web page (.html or .htm) or a PDF.")

    assert source.id is not None
    folder = new_snapshot_folder(settings.data_dir, source.program_id, source.id)
    (folder / relative).parent.mkdir(parents=True, exist_ok=True)
    (folder / relative).write_bytes(payload)
    return StagedUpload(
        folder=folder,
        kind=kind,
        filename=Path(filename).name,
        relative_path=relative,
        bytes=len(data),
    )


def decode_html(data: bytes) -> str:
    """UTF-8, else the charset the page declares (e.g. windows-1256), else Latin-1."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    match = _CHARSET.search(data[:4096])
    if match is not None:
        try:
            return data.decode(match.group(1).decode("ascii"))
        except (LookupError, UnicodeDecodeError):
            pass
    return data.decode("latin-1")


async def run_import_job(
    engine: Engine, settings: Settings, job_id: int, source_id: int, staged: StagedUpload
) -> JobStatus:
    with Session(engine) as session:
        source = session.get(ProgramSource, source_id)
        if source is None:
            raise LookupError(f"source {source_id} not found")
    item = SourceProgress(
        source_id=source_id, url=source.url, role=source.role, state=SourceState.FETCHING
    )
    progress = JobProgress(sources=[item])
    save_progress(engine, job_id, progress)

    if staged.kind == "html":
        result = await _import_html(settings, source.url, staged)
    else:
        result = _import_pdf(source.url, staged)
    write_meta(staged.folder, result.meta)

    with Session(engine) as session:
        snapshot = repo.add_snapshot(session, snapshot_row(settings, source, result))
    item.state, item.snapshot_id = SourceState.IMPORTED, snapshot.id
    item.reason = f"uploaded {staged.filename}"
    save_progress(engine, job_id, progress)
    return JobStatus.SUCCEEDED


async def _import_html(settings: Settings, url: str, staged: StagedUpload) -> SnapshotResult:
    html = (staged.folder / PAGE_HTML).read_text(encoding="utf-8")
    text = html_to_text(html)
    meta = _meta(url, staged)
    meta.title = page_title(html)
    meta.html_bytes = len(html.encode("utf-8"))
    meta.content_hash, meta.text_chars = content_hash(text), len(text)
    (staged.folder / TEXT).write_text(text, encoding="utf-8")
    files = SnapshotFiles(html=PAGE_HTML, text=TEXT)
    try:
        async with async_playwright() as pw:
            browser = await launch_browser(pw, settings.browser_channel)
            meta.browser = browser_info(browser, settings.browser_channel)
            try:
                visible = await _render_offline(browser, html, staged.folder / SCREENSHOT)
            finally:
                await browser.close()
    except PlaywrightError as exc:
        log.warning("offline render failed: %s", exc)
        meta.error = "offline render failed; visible text and screenshot unavailable"
        return SnapshotResult(folder=staged.folder, meta=meta, files=files)
    (staged.folder / VISIBLE_TEXT).write_text(visible, encoding="utf-8")
    files.visible_text, files.screenshot = VISIBLE_TEXT, SCREENSHOT
    meta.visible_text_chars, meta.screenshot = len(visible), True
    return SnapshotResult(folder=staged.folder, meta=meta, files=files)


async def _render_offline(browser: Browser, html: str, screenshot: Path) -> str:
    context = await browser.new_context(java_script_enabled=False)

    async def block(route: Route) -> None:
        await route.abort()

    try:
        await context.route("**/*", block)
        page = await context.new_page()
        await page.set_content(html, wait_until="domcontentloaded", timeout=RENDER_TIMEOUT_MS)
        await page.evaluate(OPEN_DETAILS_JS)
        visible = await page.evaluate("document.body ? document.body.innerText : ''")
        await page.screenshot(path=screenshot, full_page=True, timeout=RENDER_TIMEOUT_MS)
    finally:
        await context.close()
    return normalise_lines(visible)


def _import_pdf(url: str, staged: StagedUpload) -> SnapshotResult:
    data = (staged.folder / staged.relative_path).read_bytes()
    meta = _meta(url, staged)
    meta.content_hash = hashlib.sha256(data).hexdigest()
    meta.pdf_files = [
        SavedFile(path=staged.relative_path, url=f"upload:{staged.filename}", bytes=len(data))
    ]
    return SnapshotResult(folder=staged.folder, meta=meta, files=SnapshotFiles())


def _meta(url: str, staged: StagedUpload) -> SnapshotMeta:
    return SnapshotMeta(
        url=url,
        outcome=FetchOutcome.MANUAL_IMPORT,
        reason=f"uploaded {staged.filename}",
        imported_manually=True,
    )
