"""Browser-free fetch helpers: text, block rules, robots, throttle, site rule, meta."""

import asyncio
from types import SimpleNamespace

import pytest

from verigrad.core.fetch.blocking import PageSignals, classify
from verigrad.core.fetch.models import BrowserInfo, SnapshotMeta
from verigrad.core.fetch.polite import DomainThrottle, RobotsChecker, same_site, site_key
from verigrad.core.fetch.snapshot import browser_info
from verigrad.core.fetch.text import content_hash, html_to_text, page_title
from verigrad.core.store.models import FetchOutcome

LONG_TEXT = "Application deadline for international applicants is 1 March 2027. " * 10

# --- text --------------------------------------------------------------------------------


def test_html_to_text_keeps_hidden_text_and_drops_scripts() -> None:
    html = """<html><head><title> Fees </title><style>.x{}</style></head><body>
      <p>Deadline: <b>1 March</b></p>
      <div style="display:none">HIDDEN NOTE</div>
      <script>var tracking = 1;</script>
      <table><tr><th>Round</th><th>Date</th></tr><tr><td>Fall 2</td><td>15 Jan</td></tr></table>
      line one<br>line two
    </body></html>"""
    text = html_to_text(html)
    assert text.splitlines() == [
        "Deadline: 1 March",
        "HIDDEN NOTE",
        "Round | Date",
        "Fall 2 | 15 Jan",
        "line one",
        "line two",
    ]
    assert "tracking" not in text
    assert page_title(html) == "Fees"


def test_html_to_text_handles_empty_document() -> None:
    assert html_to_text("") == ""
    assert page_title("<p>no title</p>") == ""


def test_content_hash_ignores_whitespace_only() -> None:
    assert content_hash("a  b\n c") == content_hash("a b c")
    assert content_hash("a b c") != content_hash("a b d")


# --- block classification ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("signals", "outcome", "reason"),
    [
        (PageSignals(status=200, visible_text=LONG_TEXT), FetchOutcome.SUCCESS, None),
        (PageSignals(status=None), FetchOutcome.FAILED, "no_response"),
        (PageSignals(status=403, visible_text=LONG_TEXT), FetchOutcome.BLOCKED, "http_403"),
        (PageSignals(status=429), FetchOutcome.BLOCKED, "http_429"),
        (PageSignals(status=503), FetchOutcome.BLOCKED, "http_503"),
        (PageSignals(status=404, visible_text=LONG_TEXT), FetchOutcome.FAILED, "http_404"),
        (PageSignals(status=500), FetchOutcome.FAILED, "http_500"),
        (
            PageSignals(status=200, title="Just a moment...", visible_text=LONG_TEXT),
            FetchOutcome.BLOCKED,
            "challenge_page",
        ),
        (
            PageSignals(status=200, visible_text="Checking your browser before accessing uni.edu"),
            FetchOutcome.BLOCKED,
            "challenge_page",
        ),
        (
            PageSignals(
                status=200, visible_text="Sign in. Username Password " * 3, has_password_field=True
            ),
            FetchOutcome.BLOCKED,
            "login_wall",
        ),
        (
            PageSignals(
                status=200,
                visible_text=LONG_TEXT * 3,
                has_password_field=True,
                final_url="https://uni.example/sso/login?next=/msc",
            ),
            FetchOutcome.BLOCKED,
            "login_wall",
        ),
        (PageSignals(status=200, visible_text="Loading…"), FetchOutcome.BLOCKED, "near_empty"),
    ],
)
def test_classify(signals: PageSignals, outcome: FetchOutcome, reason: str | None) -> None:
    verdict = classify(signals)
    assert (verdict.outcome, verdict.reason) == (outcome, reason)


def test_long_page_mentioning_captcha_is_not_a_challenge() -> None:
    text = LONG_TEXT * 5 + " Our contact form uses a captcha."
    assert classify(PageSignals(status=200, visible_text=text)).outcome == FetchOutcome.SUCCESS


def test_long_page_with_header_login_widget_is_not_a_login_wall() -> None:
    signals = PageSignals(
        status=200,
        visible_text=LONG_TEXT * 3,
        has_password_field=True,
        final_url="https://uni.example/msc",
    )
    assert classify(signals).outcome == FetchOutcome.SUCCESS


# --- site rule ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "key"),
    [
        ("cs.kaust.edu.sa", "kaust.edu.sa"),
        ("admissions.kaust.edu.sa", "kaust.edu.sa"),
        ("www.master-ediss.eu", "master-ediss.eu"),
        ("ms.kfupm.edu.sa", "kfupm.edu.sa"),
        ("www.uni.ac.uk", "uni.ac.uk"),
        ("uni.ac.uk", "uni.ac.uk"),
        ("foo.example.com", "example.com"),
        ("WWW.Example.COM.", "example.com"),
        ("localhost", "localhost"),
        ("127.0.0.1", "127.0.0.1"),
    ],
)
def test_site_key(host: str, key: str) -> None:
    assert site_key(host) == key


def test_same_site() -> None:
    assert same_site("https://ms.kfupm.edu.sa/x", "https://www.kfupm.edu.sa/rules.pdf")
    assert not same_site("https://www.master-ediss.eu/", "https://www.aalto.fi/x.pdf")
    assert not same_site("http://127.0.0.1:8000/", "http://localhost:8000/")


# --- robots.txt --------------------------------------------------------------------------


def _robots(responses: dict[str, tuple[int | None, str]]) -> tuple[RobotsChecker, list[str]]:
    calls: list[str] = []

    async def fetch(url: str) -> tuple[int | None, str]:
        calls.append(url)
        return responses[url]

    return RobotsChecker(fetch), calls


def test_robots_disallow_and_cache() -> None:
    body = "User-agent: *\nDisallow: /private/\nCrawl-delay: 7\n"
    checker, calls = _robots({"https://u.example/robots.txt": (200, body)})

    async def run() -> None:
        ok = await checker.check("https://u.example/msc")
        assert ok.allowed and ok.crawl_delay == 7.0
        blocked = await checker.check("https://u.example/private/page")
        assert not blocked.allowed and blocked.reason == "robots_disallowed"

    asyncio.run(run())
    assert calls == ["https://u.example/robots.txt"]  # fetched once per origin


@pytest.mark.parametrize(
    ("status", "allowed", "reason"),
    [
        (404, True, None),
        (403, True, None),  # RFC 9309: 4xx = no rules
        (500, False, "robots_unavailable"),
        (None, True, None),  # network failure: the page fetch reports the real error
    ],
)
def test_robots_status_handling(status: int | None, allowed: bool, reason: str | None) -> None:
    checker, _ = _robots({"https://u.example/robots.txt": (status, "")})
    verdict = asyncio.run(checker.check("https://u.example/msc"))
    assert (verdict.allowed, verdict.reason) == (allowed, reason)


# --- per-domain throttle -----------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_throttle_shares_delay_across_hosts_of_one_domain() -> None:
    clock = FakeClock()
    throttle = DomainThrottle(3.0, clock=clock, sleep=clock.sleep)

    async def run() -> None:
        assert await throttle.wait("https://cs.kaust.edu.sa/") == 0
        clock.now += 1.0
        assert await throttle.wait("https://admissions.kaust.edu.sa/t") == pytest.approx(2.0)
        assert await throttle.wait("https://www.master-ediss.eu/") == 0  # other site: no wait
        clock.now += 10.0
        assert await throttle.wait("https://cs.kaust.edu.sa/x") == 0  # delay already passed

    asyncio.run(run())
    assert clock.sleeps == [pytest.approx(2.0)]


def test_throttle_honours_longer_crawl_delay() -> None:
    clock = FakeClock()
    throttle = DomainThrottle(3.0, clock=clock, sleep=clock.sleep)

    async def run() -> None:
        await throttle.wait("https://u.example/a")
        assert await throttle.wait("https://u.example/b", min_delay=7.0) == pytest.approx(7.0)

    asyncio.run(run())


# --- meta: browser info ------------------------------------------------------------------


def _fake_browser(name: str, version: str) -> SimpleNamespace:
    return SimpleNamespace(browser_type=SimpleNamespace(name=name), version=version)


def test_browser_info_bundled_chromium_has_no_channel() -> None:
    info = browser_info(_fake_browser("chromium", "141.0.7390.37"), "")  # type: ignore[arg-type]
    assert info == BrowserInfo(name="chromium", version="141.0.7390.37", channel=None)


def test_browser_info_records_an_installed_channel() -> None:
    info = browser_info(_fake_browser("chromium", "141.0.3537.71"), "msedge")  # type: ignore[arg-type]
    assert (info.channel, info.version) == ("msedge", "141.0.3537.71")


def test_meta_json_written_before_browser_info_still_loads() -> None:
    meta = SnapshotMeta.model_validate({"url": "https://example.edu/", "outcome": "SUCCESS"})
    assert meta.browser is None
