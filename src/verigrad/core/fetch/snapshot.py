"""Snapshot one source URL into a folder (spec §3.4, decisions D6/D8). No AI involved.

Folder contents: page.html, text.txt, visible_text.txt, screenshot.png, json/, pdfs/, meta.json.
BLOCKED and FAILED attempts still write meta.json (and whatever could be captured) as evidence.
"""

import asyncio
import logging
import re
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

from playwright.async_api import (
    APIRequestContext,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Response,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from verigrad.core.fetch.blocking import PageSignals, classify
from verigrad.core.fetch.models import (
    JSON_DIR,
    META,
    PAGE_HTML,
    PDF_DIR,
    SCREENSHOT,
    TEXT,
    VISIBLE_TEXT,
    BrowserInfo,
    SavedFile,
    SkippedLink,
    SnapshotFiles,
    SnapshotMeta,
    SnapshotResult,
)
from verigrad.core.fetch.polite import DomainThrottle, RobotsChecker, RobotsFetcher, same_site
from verigrad.core.fetch.prepare import prepare_page
from verigrad.core.fetch.text import content_hash, html_to_text, normalise_lines
from verigrad.core.store.models import FetchOutcome

log = logging.getLogger(__name__)

MAX_JSON_FILES = 50
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_PDF_FILES = 10
MAX_PDF_BYTES = 20 * 1024 * 1024

_VISIBLE_PASSWORD_JS = """
() => Array.from(document.querySelectorAll('input[type="password"]'))
  .some(el => el.getClientRects().length > 0)
"""
_PDF_LINKS_JS = """
() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)
"""


async def launch_browser(pw: Playwright, channel: str = "") -> Browser:
    """Playwright's Chromium with default settings: headless, default user agent, no stealth
    (D8). `channel` ("msedge"/"chrome") uses an installed browser instead of the bundled one."""
    return await pw.chromium.launch(channel=channel or None)


def browser_info(browser: Browser, channel: str) -> BrowserInfo:
    """Name, version and channel of a launched browser, for meta.json."""
    return BrowserInfo(
        name=browser.browser_type.name, version=browser.version, channel=channel or None
    )


def robots_fetcher(api: APIRequestContext, timeout_s: float) -> RobotsFetcher:
    """robots.txt over the same Playwright network stack the pages use."""

    async def fetch(robots_url: str) -> tuple[int | None, str]:
        try:
            response = await api.get(
                robots_url, timeout=timeout_s * 1000, fail_on_status_code=False
            )
            return response.status, await response.text()
        except PlaywrightError as exc:
            log.info("robots.txt unreachable %s: %s", robots_url, _first_line(str(exc)))
            return None, ""

    return fetch


class Politeness:
    """robots.txt + per-domain delay, applied to the page and to every PDF download."""

    def __init__(self, robots: RobotsChecker, throttle: DomainThrottle) -> None:
        self.robots = robots
        self.throttle = throttle

    async def clear(self, url: str) -> str | None:
        """Wait our turn for this site; returns a refusal reason if robots.txt forbids it."""
        verdict = await self.robots.check(url)
        if not verdict.allowed:
            return verdict.reason
        await self.throttle.wait(url, verdict.crawl_delay)
        return None


async def snapshot_source(
    browser: Browser,
    url: str,
    folder: Path,
    politeness: Politeness,
    timeout_s: float,
    *,
    channel: str,
) -> SnapshotResult:
    """`channel` must be the one `browser` was launched with (recorded in meta.json)."""
    folder.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    meta = SnapshotMeta(url=url, outcome=FetchOutcome.FAILED)
    files = SnapshotFiles()

    refusal = await politeness.clear(url)
    if refusal is not None:
        meta.outcome, meta.reason = FetchOutcome.BLOCKED, refusal
        return _finish(folder, meta, files, started)

    meta.browser = browser_info(browser, channel)
    context = await browser.new_context()
    try:
        await _capture(context, url, folder, politeness, timeout_s, meta, files)
    finally:
        await context.close()
    return _finish(folder, meta, files, started)


async def _capture(
    context: BrowserContext,
    url: str,
    folder: Path,
    politeness: Politeness,
    timeout_s: float,
    meta: SnapshotMeta,
    files: SnapshotFiles,
) -> None:
    timeout_ms = int(timeout_s * 1000)
    page = await context.new_page()
    page.set_default_timeout(timeout_ms)
    json_tasks: list[asyncio.Task[None]] = []

    def on_response(response: Response) -> None:
        json_tasks.append(asyncio.ensure_future(_save_json(response, url, folder, meta)))

    page.on("response", on_response)
    try:
        await _load_and_capture(page, context, url, folder, politeness, timeout_ms, meta, files)
    finally:
        page.remove_listener("response", on_response)
        if json_tasks:
            await asyncio.gather(*json_tasks, return_exceptions=True)


async def _load_and_capture(
    page: Page,
    context: BrowserContext,
    url: str,
    folder: Path,
    politeness: Politeness,
    timeout_ms: int,
    meta: SnapshotMeta,
    files: SnapshotFiles,
) -> None:
    timeout_s = timeout_ms / 1000
    t0 = time.perf_counter()
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        meta.reason, meta.error = "timeout", f"no response within {timeout_s:.0f}s"
        return
    except PlaywrightError as exc:
        meta.reason, meta.error = _network_reason(str(exc)), _first_line(str(exc))
        return
    meta.timings_ms["navigate"] = _ms_since(t0)
    meta.http_status = response.status if response is not None else None

    t1 = time.perf_counter()
    meta.prep = await prepare_page(page)
    meta.timings_ms["prepare"] = _ms_since(t1)

    t2 = time.perf_counter()
    meta.final_url = page.url
    html = await page.content()
    visible = normalise_lines(await page.evaluate("document.body ? document.body.innerText : ''"))
    meta.title = await page.title()
    has_password = bool(await page.evaluate(_VISIBLE_PASSWORD_JS))
    text = html_to_text(html)

    files.html = _write(folder / PAGE_HTML, html)
    files.text = _write(folder / TEXT, text)
    files.visible_text = _write(folder / VISIBLE_TEXT, visible)
    meta.html_bytes = len(html.encode("utf-8"))
    meta.text_chars, meta.visible_text_chars = len(text), len(visible)
    meta.content_hash = content_hash(text)
    files.screenshot = await _screenshot(page, folder, timeout_ms)
    meta.screenshot = files.screenshot is not None
    meta.timings_ms["capture"] = _ms_since(t2)

    verdict = classify(
        PageSignals(
            status=meta.http_status,
            title=meta.title,
            visible_text=visible,
            has_password_field=has_password,
            final_url=page.url,
        )
    )
    meta.outcome, meta.reason = verdict.outcome, verdict.reason

    if verdict.outcome == FetchOutcome.SUCCESS:
        t3 = time.perf_counter()
        await _save_pdfs(page, context, folder, politeness, timeout_ms, meta)
        meta.timings_ms["pdfs"] = _ms_since(t3)


async def _save_json(response: Response, page_url: str, folder: Path, meta: SnapshotMeta) -> None:
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        return
    if not same_site(response.url, page_url):
        meta.skipped_json.append(SkippedLink(url=response.url, reason="off_site"))
        return
    if len(meta.json_files) >= MAX_JSON_FILES:
        meta.skipped_json.append(SkippedLink(url=response.url, reason="cap"))
        return
    try:
        body = await response.body()
    except PlaywrightError:
        meta.skipped_json.append(SkippedLink(url=response.url, reason="error"))
        return
    if len(body) > MAX_JSON_BYTES:
        meta.skipped_json.append(SkippedLink(url=response.url, reason="too_large"))
        return
    if len(meta.json_files) >= MAX_JSON_FILES:  # other responses may have filled it meanwhile
        meta.skipped_json.append(SkippedLink(url=response.url, reason="cap"))
        return
    index = len(meta.json_files) + 1
    relative = f"{JSON_DIR}/{index:03d}_{_slug(response.url)}.json"
    (folder / JSON_DIR).mkdir(exist_ok=True)
    (folder / relative).write_bytes(body)
    meta.json_files.append(SavedFile(path=relative, url=response.url, bytes=len(body)))


async def _save_pdfs(
    page: Page,
    context: BrowserContext,
    folder: Path,
    politeness: Politeness,
    timeout_ms: int,
    meta: SnapshotMeta,
) -> None:
    try:
        hrefs: list[str] = await page.evaluate(_PDF_LINKS_JS)
    except PlaywrightError:
        return
    seen: set[str] = set()
    for href in hrefs:
        link = href.split("#", 1)[0]
        if link in seen or not urlsplit(link).path.lower().endswith(".pdf"):
            continue
        seen.add(link)
        if not same_site(link, meta.final_url or meta.url):
            meta.skipped_pdfs.append(SkippedLink(url=link, reason="off_site"))
            continue
        if len(meta.pdf_files) >= MAX_PDF_FILES:
            meta.skipped_pdfs.append(SkippedLink(url=link, reason="cap"))
            continue
        refusal = await politeness.clear(link)
        if refusal is not None:
            meta.skipped_pdfs.append(SkippedLink(url=link, reason=refusal))
            continue
        await _download_pdf(context, link, folder, timeout_ms, meta)


async def _download_pdf(
    context: BrowserContext, link: str, folder: Path, timeout_ms: int, meta: SnapshotMeta
) -> None:
    try:
        response = await context.request.get(link, timeout=timeout_ms, fail_on_status_code=False)
        if not response.ok:
            meta.skipped_pdfs.append(SkippedLink(url=link, reason=f"http_{response.status}"))
            return
        length = int(response.headers.get("content-length", "0") or 0)
        if length > MAX_PDF_BYTES:
            meta.skipped_pdfs.append(SkippedLink(url=link, reason="too_large"))
            return
        body = await response.body()
    except PlaywrightError as exc:
        log.info("pdf download failed %s: %s", link, _first_line(str(exc)))
        meta.skipped_pdfs.append(SkippedLink(url=link, reason="error"))
        return
    if len(body) > MAX_PDF_BYTES:
        meta.skipped_pdfs.append(SkippedLink(url=link, reason="too_large"))
        return
    if not body.startswith(b"%PDF"):
        meta.skipped_pdfs.append(SkippedLink(url=link, reason="not_pdf"))
        return
    index = len(meta.pdf_files) + 1
    name = _slug(unquote(urlsplit(link).path.rsplit("/", 1)[-1]).removesuffix(".pdf"))
    relative = f"{PDF_DIR}/{index:02d}_{name}.pdf"
    (folder / PDF_DIR).mkdir(exist_ok=True)
    (folder / relative).write_bytes(body)
    meta.pdf_files.append(SavedFile(path=relative, url=link, bytes=len(body)))


async def _screenshot(page: Page, folder: Path, timeout_ms: int) -> str | None:
    try:
        await page.screenshot(path=folder / SCREENSHOT, full_page=True, timeout=timeout_ms)
    except PlaywrightError as exc:
        log.info("screenshot failed: %s", _first_line(str(exc)))
        return None
    return SCREENSHOT


def _finish(
    folder: Path, meta: SnapshotMeta, files: SnapshotFiles, started: float
) -> SnapshotResult:
    meta.timings_ms["total"] = _ms_since(started)
    write_meta(folder, meta)
    log.info(
        "fetch outcome=%s reason=%s url=%s ms=%s",
        meta.outcome,
        meta.reason,
        meta.url,
        meta.timings_ms["total"],
    )
    return SnapshotResult(folder=folder, meta=meta, files=files)


def write_meta(folder: Path, meta: SnapshotMeta) -> None:
    (folder / META).write_text(meta.model_dump_json(indent=2), encoding="utf-8")


def _write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return path.name


def _network_reason(message: str) -> str:
    match = re.search(r"net::ERR_([A-Z_]+)", message)
    if match is None:
        return "error"
    code = match.group(1).lower()
    return "dns" if code == "name_not_resolved" else code


def _slug(text: str, limit: int = 60) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")
    return slug[-limit:] or "file"


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0][:300] if text.strip() else ""


def _ms_since(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
