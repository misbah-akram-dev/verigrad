"""Decide a fetch outcome from what the browser saw. Pure; tested without a browser."""

import re

from pydantic import BaseModel

from verigrad.core.store.models import FetchOutcome

NEAR_EMPTY_CHARS = 200
SHORT_PAGE_CHARS = 1500  # challenge pages and login walls are short
BLOCK_STATUSES = {403, 429, 503}

# Matched against the title, and against visible text only on short pages: a real programme
# page may mention "captcha" in a contact form. HTML markers such as Cloudflare's
# `challenge-platform` script are not used — Cloudflare injects that into normal pages too.
_CHALLENGE_TITLES = ("just a moment", "attention required", "access denied", "security check")
_CHALLENGE_TEXT = (
    "checking your browser",
    "verify you are human",
    "verifying you are human",
    "enable javascript and cookies to continue",
    "ddos protection",
    "complete the security check",
    "captcha",
)
_LOGIN_PATH = re.compile(r"/(login|log-in|signin|sign-in|sso|auth|cas)(/|$|\?)", re.IGNORECASE)


class PageSignals(BaseModel):
    status: int | None
    title: str = ""
    visible_text: str = ""
    has_password_field: bool = False
    final_url: str = ""


class Verdict(BaseModel):
    outcome: FetchOutcome
    reason: str | None = None


def classify(signals: PageSignals) -> Verdict:
    if signals.status is None:
        return Verdict(outcome=FetchOutcome.FAILED, reason="no_response")
    if signals.status in BLOCK_STATUSES:
        return Verdict(outcome=FetchOutcome.BLOCKED, reason=f"http_{signals.status}")
    if signals.status >= 400:
        return Verdict(outcome=FetchOutcome.FAILED, reason=f"http_{signals.status}")

    text = " ".join(signals.visible_text.split())
    title = signals.title.lower()
    short = len(text) < SHORT_PAGE_CHARS
    if any(marker in title for marker in _CHALLENGE_TITLES) or (
        short and any(marker in text.lower() for marker in _CHALLENGE_TEXT)
    ):
        return Verdict(outcome=FetchOutcome.BLOCKED, reason="challenge_page")
    if signals.has_password_field and (short or _LOGIN_PATH.search(signals.final_url)):
        return Verdict(outcome=FetchOutcome.BLOCKED, reason="login_wall")
    if len(text) < NEAR_EMPTY_CHARS:
        return Verdict(outcome=FetchOutcome.BLOCKED, reason="near_empty")
    return Verdict(outcome=FetchOutcome.SUCCESS)
