import pytest
from fastapi.testclient import TestClient

from verigrad.config import Settings
from verigrad.web.app import create_app
from verigrad.web.routes import NAV_PAGES


@pytest.fixture
def web(settings: Settings):  # type: ignore[no-untyped-def]
    no_key = settings.model_copy(update={"anthropic_api_key": None})
    with TestClient(create_app(no_key)) as client:
        yield client


def test_home_renders_without_api_key(web: TestClient) -> None:
    response = web.get("/")
    assert response.status_code == 200
    assert "Verigrad" in response.text
    assert "No <code>ANTHROPIC_API_KEY</code> set" in response.text
    for label in ["Add", "Tracker", "Review", "Plan", "Dashboard", "Costs"]:
        assert f">{label}</a>" in response.text


@pytest.mark.parametrize("path", [str(p["path"]) for p in NAV_PAGES])
def test_nav_pages_render(web: TestClient, path: str) -> None:
    response = web.get(path)
    assert response.status_code == 200
    assert 'aria-current="page"' in response.text


def test_startup_creates_database(settings: Settings, web: TestClient) -> None:
    assert settings.db_path.exists()


def test_no_banner_when_key_set(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        assert "No <code>ANTHROPIC_API_KEY</code>" not in client.get("/").text
