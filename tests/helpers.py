"""Test helpers: DB seeding and fake Anthropic responses."""

from types import SimpleNamespace
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session

from verigrad.core.store.models import Job, JobKind, Program


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
