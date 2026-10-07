"""Test helpers: DB seeding, fake Anthropic responses, web-flow helpers."""

import time
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session

from verigrad.core.store.models import Job, JobKind, JobStatus, Program


def wait_for_job(client: TestClient, job_id: int, timeout: float = 90) -> Job:
    """Poll the DB until a background job finishes."""
    engine = client.app.state.engine  # type: ignore[attr-defined]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with Session(engine) as session:
            job = session.get(Job, job_id)
            if job and job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish")


def submit_add_form(client: TestClient, sources: list[tuple[str, str]], name: str = "") -> int:
    """POST the Add form; returns the started job id."""
    response = client.post(
        "/add",
        data={"name": name, "url": [u for u, _ in sources], "role": [r for _, r in sources]},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    assert location.startswith("/add/jobs/")
    return int(location.rsplit("/", 1)[-1])


def job_id_from_redirect(response: Any) -> int:
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rsplit("/", 1)[-1])


def make_job(engine: Engine, program_id: int | None = None) -> int:
    with Session(engine) as session:
        job = Job(kind=JobKind.EXTRACT, program_id=program_id)
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        return job.id


def make_program(engine: Engine, url: str = "https://uni.example/msc") -> int:
    with Session(engine) as session:
        program = Program(url=url)
        session.add(program)
        session.commit()
        session.refresh(program)
        assert program.id is not None
        return program.id


def fake_message(
    input_tokens: int = 1000,
    output_tokens: int = 500,
    request_id: str = "req_test_123",
    **usage_extra: Any,
) -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=usage_extra.get("cache_creation_input_tokens"),
        cache_read_input_tokens=usage_extra.get("cache_read_input_tokens"),
    )
    return SimpleNamespace(
        usage=usage,
        _request_id=request_id,
        content=[SimpleNamespace(type="text", text="ok")],
        stop_reason="end_turn",
    )
