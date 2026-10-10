"""Browser tests: real Chromium against the local fixture site (no internet)."""

import asyncio
import json
import socket
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from fixture_site import BROWSER_CHANNEL, FixtureSite
from verigrad.core.fetch.models import RevealedPanels, SnapshotMeta, SnapshotResult
from verigrad.core.fetch.polite import DomainThrottle, RobotsChecker
from verigrad.core.fetch.snapshot import (
    Politeness,
    launch_browser,
    robots_fetcher,
    snapshot_source,
)
from verigrad.core.store.models import FetchOutcome

pytestmark = [pytest.mark.browser, pytest.mark.usefixtures("chromium")]


async def _snapshot(url: str, folder: Path) -> SnapshotResult:
    async with async_playwright() as pw:
        browser = await launch_browser(pw, BROWSER_CHANNEL)
        api = await pw.request.new_context()
        try:
            politeness = Politeness(RobotsChecker(robots_fetcher(api, 10)), DomainThrottle(0))
            return await snapshot_source(
                browser, url, folder, politeness, timeout_s=15, channel=BROWSER_CHANNEL
            )
        finally:
            await api.dispose()
            await browser.close()


def snap(site: FixtureSite, path: str, tmp_path: Path) -> SnapshotResult:
    return asyncio.run(_snapshot(site.url(path), tmp_path / "snap"))


def read(result: SnapshotResult, name: str) -> str:
    return (result.folder / name).read_text(encoding="utf-8")


def test_normal_page(site: FixtureSite, tmp_path: Path) -> None:
    result = snap(site, "normal.html", tmp_path)
    meta = result.meta
    assert (meta.outcome, meta.reason, meta.http_status) == (FetchOutcome.SUCCESS, None, 200)
    for name in ("page.html", "text.txt", "visible_text.txt", "screenshot.png", "meta.json"):
        assert (result.folder / name).exists(), name
    assert "International | 15 January 2027" in read(result, "text.txt")
    assert "15 January 2027" in read(result, "visible_text.txt")
    assert meta.prep.cookie_banner_dismissed
    assert meta.title == "MSc Data Science — Example University"
    assert meta.content_hash and meta.screenshot
    saved = SnapshotMeta.model_validate(json.loads(read(result, "meta.json")))
    assert saved.outcome == FetchOutcome.SUCCESS and saved.timings_ms["total"] > 0
    assert saved.browser is not None and saved.browser.name == "chromium"
    assert saved.browser.version and saved.browser.channel == (BROWSER_CHANNEL or None)


def test_accordions_are_expanded_and_navigation_is_undone(
    site: FixtureSite, tmp_path: Path
) -> None:
    result = snap(site, "accordion.html", tmp_path)
    meta = result.meta
    visible = read(result, "visible_text.txt")
    assert meta.outcome == FetchOutcome.SUCCESS
    assert meta.final_url == site.url("accordion.html")
    for marker in ("DETAILS_SECRET", "TOGGLE_ONE", "TOGGLE_TWO"):
        assert marker in visible, marker
    assert "AWAY_PAGE" not in read(result, "text.txt")
    assert meta.prep.details_opened == 1
    assert meta.prep.toggles_clicked >= 2
    assert [u.endswith("/away.html") for u in meta.prep.navigated_away] == [True]
    assert not meta.prep.expansion_stopped
    assert site.hits["/away2.html"] == 0  # generic role=button is never clicked
    assert site.hits["/menu.html"] == 0  # toggles inside <header> are skipped


@pytest.mark.parametrize(
    ("path", "markers", "decoys", "revealed"),
    [
        # KFUPM: "collapsed" buttons with aria-expanded="true" are never clicked.
        (
            "mismatched_accordion.html",
            ["ACC_ONE", "ACC_TWO", "ACC_THREE"],
            ["NAV_MENU", "ORPHAN_COLLAPSE", "HIDDEN_PARAGRAPH"],
            RevealedPanels(collapse=3),
        ),
        # KAUST: only the active tab renders; the tab list sits in a <nav>.
        (
            "tabs.html",
            ["TAB_ONE", "TAB_TWO", "TAB_THREE"],
            ["CHAT_WIDGET", "HIDDEN_PARAGRAPH"],
            RevealedPanels(tab=2),
        ),
        # EDISS: one-open-at-a-time accordion; clicking leaves only the last section open.
        (
            "single_open_accordion.html",
            [f"COUNTRY_{i}" for i in range(1, 6)],
            ["HIDDEN_PARAGRAPH"],
            RevealedPanels(collapse=4),
        ),
    ],
)
def test_panels_are_revealed_but_hidden_text_stays_hidden(
    site: FixtureSite,
    tmp_path: Path,
    path: str,
    markers: list[str],
    decoys: list[str],
    revealed: RevealedPanels,
) -> None:
    result = snap(site, path, tmp_path)
    meta = result.meta
    visible, text = read(result, "visible_text.txt"), read(result, "text.txt")
    assert meta.outcome == FetchOutcome.SUCCESS
    assert meta.prep.navigated_away == []
    for marker in markers:
        assert marker in visible, marker
    for decoy in decoys:
        assert decoy in text, decoy
        assert decoy not in visible, decoy
    assert meta.prep.panels_revealed == revealed
    assert 'data-verigrad-revealed="' in read(result, "page.html")


def test_same_site_json_is_saved_third_party_is_skipped(site: FixtureSite, tmp_path: Path) -> None:
    result = snap(site, "json.html", tmp_path)
    meta = result.meta
    assert meta.outcome == FetchOutcome.SUCCESS
    assert "JSON_ROUND 15 January 2027" in read(result, "visible_text.txt")
    assert [f.url for f in meta.json_files] == [site.url("api/deadlines.json")]
    saved = json.loads((result.folder / meta.json_files[0].path).read_text(encoding="utf-8"))
    assert saved["rounds"][0]["name"] == "Round 1"
    skipped = {(s.url.split("/")[-1], s.reason) for s in meta.skipped_json}
    assert ("tracking.json", "off_site") in skipped


def test_same_site_pdf_is_saved_off_site_pdf_is_skipped(site: FixtureSite, tmp_path: Path) -> None:
    result = snap(site, "pdf.html", tmp_path)
    meta = result.meta
    assert meta.outcome == FetchOutcome.SUCCESS
    assert len(meta.pdf_files) == 1  # `rules.pdf#page=2` is the same file
    pdf = meta.pdf_files[0]
    assert pdf.path == "pdfs/01_rules.pdf"
    assert (result.folder / pdf.path).read_bytes().startswith(b"%PDF")
    assert [(s.url, s.reason) for s in meta.skipped_pdfs] == [
        ("https://partner.example.org/brochure.pdf", "off_site")
    ]


def test_hidden_text_is_in_text_but_not_visible_text(site: FixtureSite, tmp_path: Path) -> None:
    result = snap(site, "hidden.html", tmp_path)
    assert result.meta.outcome == FetchOutcome.SUCCESS
    assert "HIDDEN_INSTRUCTION" in read(result, "text.txt")
    assert "HIDDEN_INSTRUCTION" not in read(result, "visible_text.txt")
    assert "15 January 2027" in read(result, "visible_text.txt")


@pytest.mark.parametrize(
    ("path", "outcome", "reason"),
    [
        ("challenge.html", FetchOutcome.BLOCKED, "challenge_page"),
        ("forbidden", FetchOutcome.BLOCKED, "http_403"),
        ("empty.html", FetchOutcome.BLOCKED, "near_empty"),
        ("login.html", FetchOutcome.BLOCKED, "login_wall"),
        ("server-error", FetchOutcome.FAILED, "http_500"),
        ("missing.html", FetchOutcome.FAILED, "http_404"),
    ],
)
def test_blocked_and_failed_pages_keep_evidence(
    site: FixtureSite, tmp_path: Path, path: str, outcome: FetchOutcome, reason: str
) -> None:
    result = snap(site, path, tmp_path)
    assert (result.meta.outcome, result.meta.reason) == (outcome, reason)
    assert (result.folder / "meta.json").exists()
    assert (result.folder / "page.html").exists()  # evidence for the user
    assert result.meta.pdf_files == []


def test_robots_disallowed_page_is_never_requested(site: FixtureSite, tmp_path: Path) -> None:
    result = snap(site, "private/page.html", tmp_path)
    assert (result.meta.outcome, result.meta.reason) == (
        FetchOutcome.BLOCKED,
        "robots_disallowed",
    )
    assert site.hits["/private/page.html"] == 0
    assert not (result.folder / "page.html").exists()
    assert (result.folder / "meta.json").exists()
    assert result.meta.browser is None  # no browser touched the page


def test_unreachable_host_fails_with_the_network_reason(tmp_path: Path) -> None:
    with socket.socket() as probe:  # a free port that nothing listens on once closed
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    result = asyncio.run(_snapshot(f"http://127.0.0.1:{port}/", tmp_path / "snap"))
    assert (result.meta.outcome, result.meta.reason) == (
        FetchOutcome.FAILED,
        "connection_refused",
    )
    assert result.meta.error
