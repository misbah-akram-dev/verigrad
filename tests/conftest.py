"""Shared fixtures. No test here talks to the real Anthropic API (except `live` ones) or the
internet: browser tests fetch from a local fixture site."""

import asyncio
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright
from sqlalchemy import Engine

from fixture_site import BROWSER_CHANNEL, FixtureSite, serve_fixture_site
from helpers import fake_message
from verigrad.config import Settings
from verigrad.core.store.db import init_db, make_engine
from verigrad.web.app import create_app

INSTALL_HINT = (
    "Chromium not installed: run `uv run playwright install chromium` "
    "(or set VERIGRAD_BROWSER_CHANNEL=msedge)"
)


async def _chromium_launches() -> bool:
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(channel=BROWSER_CHANNEL or None)
        except PlaywrightError:
            return False
        await browser.close()
        return True


@pytest.fixture(scope="session")
def chromium() -> None:
    """Browser tests depend on this: skip (with the install command) if Chromium is missing."""
    if not asyncio.run(_chromium_launches()):
        pytest.skip(INSTALL_HINT)


@pytest.fixture(scope="session")
def site() -> Iterator[FixtureSite]:
    with serve_fixture_site() as fixture_site:
        yield fixture_site


@pytest.fixture
def settings(tmp_path) -> Settings:  # type: ignore[no-untyped-def]
    return Settings(
        _env_file=None,
        anthropic_api_key="sk-test-not-real",
        extract_model="claude-sonnet-5-5",
        max_cost_per_job=0.30,
        llm_timeout_seconds=120,
        data_dir=tmp_path,
        db_path=tmp_path / "test.db",
        fetch_delay_seconds=0,
        fetch_timeout_seconds=15,
        browser_channel=BROWSER_CHANNEL,
    )


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    eng = make_engine(f"sqlite:///{settings.db_path}")
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """The web app with its real job runner, on a temp data dir."""
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def mock_sdk() -> MagicMock:
    sdk = MagicMock(name="anthropic_client")
    sdk.messages.create.return_value = fake_message()
    return sdk
