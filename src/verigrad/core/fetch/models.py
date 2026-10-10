"""Models crossing the fetch boundary: what a snapshot attempt produced (written as meta.json)."""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from verigrad.core.store.models import FetchOutcome, utcnow


class RevealedPanels(BaseModel):
    """Hidden panels made visible because a visible toggle on the page points at them (D32)."""

    collapse: int = 0  # accordion/collapse panels (Bootstrap .collapse, plugin variants)
    tab: int = 0  # inactive tab panels
    disclosure: int = 0  # other aria-controls targets (e.g. `hidden` panels)

    @property
    def total(self) -> int:
        return self.collapse + self.tab + self.disclosure


class PrepStats(BaseModel):
    """What page preparation did before capture (all best-effort)."""

    settled: bool = False  # network went idle before the settle timeout
    cookie_banner_dismissed: bool = False
    details_opened: int = 0
    toggles_clicked: int = 0
    navigated_away: list[str] = Field(default_factory=list)  # URLs a click took us to; we went back
    expansion_stopped: bool = False
    panels_revealed: RevealedPanels = Field(default_factory=RevealedPanels)


class BrowserInfo(BaseModel):
    """The browser that rendered the page: rendering (and so the captured text) can change
    between browser builds, so every snapshot records which one it came from."""

    name: str  # Playwright browser type, e.g. "chromium"
    version: str  # e.g. "141.0.7390.37"
    channel: str | None = None  # "msedge"/"chrome" = installed browser; None = Playwright's own


class SavedFile(BaseModel):
    path: str  # relative to the snapshot folder
    url: str
    bytes: int


class SkippedLink(BaseModel):
    url: str
    reason: str  # off_site | too_large | cap | robots_* | not_pdf | http_<status> | error


class SnapshotMeta(BaseModel):
    url: str
    final_url: str | None = None
    http_status: int | None = None
    outcome: FetchOutcome
    reason: str | None = None
    error: str | None = None
    imported_manually: bool = False
    browser: BrowserInfo | None = None  # None when no browser rendered it (robots refusal, PDF)
    fetched_at: datetime = Field(default_factory=utcnow)
    timings_ms: dict[str, int] = Field(default_factory=dict)
    title: str = ""
    content_hash: str | None = None
    html_bytes: int = 0
    text_chars: int = 0
    visible_text_chars: int = 0
    screenshot: bool = False
    prep: PrepStats = Field(default_factory=PrepStats)
    json_files: list[SavedFile] = Field(default_factory=list)
    skipped_json: list[SkippedLink] = Field(default_factory=list)
    pdf_files: list[SavedFile] = Field(default_factory=list)
    skipped_pdfs: list[SkippedLink] = Field(default_factory=list)


class SnapshotFiles(BaseModel):
    """File names inside one snapshot folder (None = not produced)."""

    html: str | None = None
    text: str | None = None
    visible_text: str | None = None
    screenshot: str | None = None
    meta: str = "meta.json"


class SnapshotResult(BaseModel):
    folder: Path
    meta: SnapshotMeta
    files: SnapshotFiles


PAGE_HTML = "page.html"
TEXT = "text.txt"
VISIBLE_TEXT = "visible_text.txt"
SCREENSHOT = "screenshot.png"
META = "meta.json"
JSON_DIR = "json"
PDF_DIR = "pdfs"
