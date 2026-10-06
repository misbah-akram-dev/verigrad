"""Shared fixtures. No test here talks to the real Anthropic API (except `live` ones)."""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Engine

from helpers import fake_message
from verigrad.config import Settings
from verigrad.core.store.db import init_db, make_engine


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
    )


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    eng = make_engine(f"sqlite:///{settings.db_path}")
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def mock_sdk() -> MagicMock:
    sdk = MagicMock(name="anthropic_client")
    sdk.messages.create.return_value = fake_message()
    return sdk
