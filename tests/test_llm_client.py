"""LLMClient: logging, per-job cost guard, purposes, configuration. SDK is mocked."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from helpers import fake_message, make_job, make_program
from verigrad.config import Settings
from verigrad.core.llm import (
    BudgetExceededError,
    LLMClient,
    LLMNotConfiguredError,
    UnknownModelError,
)
from verigrad.core.llm import client as client_module
from verigrad.core.store.models import LLMCall

MESSAGES = [{"role": "user", "content": "Hello"}]


def seed_spend(
    engine: Engine, cost: float, job_id: int | None, program_id: int | None = None
) -> None:
    with Session(engine) as session:
        session.add(
            LLMCall(
                purpose="extract",
                model="claude-sonnet-5-5",
                input_tokens=0,
                output_tokens=0,
                cost_usd=cost,
                estimated_cost_usd=cost,
                latency_ms=1,
                job_id=job_id,
                program_id=program_id,
            )
        )
        session.commit()


def rows(engine: Engine) -> list[LLMCall]:
    with Session(engine) as session:
        return list(session.exec(select(LLMCall).order_by(LLMCall.id)))


@pytest.fixture
def client(settings: Settings, engine: Engine, mock_sdk: MagicMock) -> LLMClient:
    return LLMClient(settings, engine, sdk_client=mock_sdk, sleep=lambda _s: None)


def test_logs_call_with_cost_estimate_tokens_and_ids(
    client: LLMClient, engine: Engine, mock_sdk: MagicMock
) -> None:
    program_id = make_program(engine)
    job_id = make_job(engine, program_id)
    mock_sdk.messages.create.return_value = fake_message(20_000, 3_000, request_id="req_abc")

    result = client.complete(
        purpose="extract", messages=MESSAGES, system="sys", job_id=job_id, program_id=program_id
    )

    # Sonnet 5.5: 20k × $2/M + 3k × $10/M = $0.07
    assert result.cost_usd == Decimal("0.07")
    assert result.request_id == "req_abc"
    assert result.over_budget is False
    [row] = rows(engine)
    assert row.purpose == "extract"
    assert row.model == "claude-sonnet-5-5"
    assert (row.input_tokens, row.output_tokens) == (20_000, 3_000)
    assert row.cost_usd == pytest.approx(0.07)
    assert row.estimated_cost_usd > 0
    assert row.estimated_cost_usd == pytest.approx(float(result.estimated_cost_usd), abs=1e-6)
    assert row.request_id == "req_abc"
    assert (row.job_id, row.program_id) == (job_id, program_id)
    assert row.latency_ms >= 0

    sent = mock_sdk.messages.create.call_args.kwargs
    assert sent["model"] == "claude-sonnet-5-5"
    assert sent["system"] == "sys"
    assert sent["messages"] == MESSAGES


def test_estimate_uses_expected_output_tokens(client: LLMClient) -> None:
    small = client.complete(purpose="smoke", messages=MESSAGES, expected_output_tokens=100)
    large = client.complete(purpose="smoke", messages=MESSAGES, expected_output_tokens=10_000)
    # 9,900 extra output tokens × $10/M = $0.099
    assert large.estimated_cost_usd - small.estimated_cost_usd == Decimal("0.099")


def test_guard_blocks_call_when_job_spend_near_budget(
    client: LLMClient, engine: Engine, mock_sdk: MagicMock
) -> None:
    job_id = make_job(engine)
    seed_spend(engine, 0.28, job_id)  # + ~$0.04 estimate > $0.30

    with pytest.raises(BudgetExceededError) as info:
        client.complete(purpose="extract", messages=MESSAGES, job_id=job_id)

    assert info.value.job_id == job_id
    assert info.value.spent == Decimal("0.28")
    mock_sdk.messages.create.assert_not_called()
    assert len(rows(engine)) == 1  # nothing new logged


def test_guard_sums_spend_by_job_not_other_jobs(
    client: LLMClient, engine: Engine, mock_sdk: MagicMock
) -> None:
    job_a = make_job(engine)
    job_b = make_job(engine)
    seed_spend(engine, 0.29, job_b)

    client.complete(purpose="extract", messages=MESSAGES, job_id=job_a)
    mock_sdk.messages.create.assert_called_once()


def test_guard_ignores_same_programme_spend_under_other_jobs(
    client: LLMClient, engine: Engine, mock_sdk: MagicMock
) -> None:
    program_id = make_program(engine)
    old_job = make_job(engine, program_id)
    new_job = make_job(engine, program_id)
    seed_spend(engine, 5.00, old_job, program_id)  # e.g. many earlier eval runs

    client.complete(purpose="eval", messages=MESSAGES, job_id=new_job, program_id=program_id)
    mock_sdk.messages.create.assert_called_once()


def test_call_without_job_id_skips_guard(
    client: LLMClient, engine: Engine, mock_sdk: MagicMock
) -> None:
    seed_spend(engine, 100.0, None)  # lots of unscoped spend

    result = client.complete(purpose="smoke", messages=MESSAGES, expected_output_tokens=1_000_000)

    mock_sdk.messages.create.assert_called_once()
    assert result.over_budget is False
    assert rows(engine)[-1].job_id is None


def test_over_budget_flagged_after_call(
    client: LLMClient, engine: Engine, mock_sdk: MagicMock
) -> None:
    job_id = make_job(engine)
    seed_spend(engine, 0.20, job_id)
    # Estimate is small (100 output tokens) so the guard lets it through…
    # …but the actual response is big: 10k out × $10/M = $0.10 → $0.30 + input > budget.
    mock_sdk.messages.create.return_value = fake_message(1_000, 10_000)

    result = client.complete(
        purpose="extract", messages=MESSAGES, job_id=job_id, expected_output_tokens=100
    )
    assert result.over_budget is True


def test_label_purpose_is_accepted(client: LLMClient, engine: Engine) -> None:
    client.complete(purpose="label", messages=MESSAGES, model="claude-opus-5-5")
    assert rows(engine)[-1].purpose == "label"
    assert rows(engine)[-1].model == "claude-opus-5-5"


def test_invalid_purpose_is_rejected(client: LLMClient, mock_sdk: MagicMock) -> None:
    with pytest.raises(ValueError, match="purpose"):
        client.complete(purpose="chat", messages=MESSAGES)  # type: ignore[arg-type]
    mock_sdk.messages.create.assert_not_called()


def test_unknown_model_rejected_before_any_call(
    client: LLMClient, engine: Engine, mock_sdk: MagicMock
) -> None:
    with pytest.raises(UnknownModelError):
        client.complete(purpose="extract", messages=MESSAGES, model="claude-fable-5-1")
    mock_sdk.messages.create.assert_not_called()
    assert rows(engine) == []


def test_retries_go_through_wrapper_and_log_once(
    client: LLMClient, engine: Engine, mock_sdk: MagicMock
) -> None:
    import anthropic
    import httpx2

    response = httpx2.Response(
        429, headers={"retry-after": "1"}, request=httpx2.Request("POST", "https://x")
    )
    mock_sdk.messages.create.side_effect = [
        anthropic.RateLimitError("slow down", response=response, body=None),
        fake_message(),
    ]
    client.complete(purpose="extract", messages=MESSAGES)
    assert mock_sdk.messages.create.call_count == 2
    assert len(rows(engine)) == 1


def test_missing_api_key_raises_only_when_calling(settings: Settings, engine: Engine) -> None:
    no_key = settings.model_copy(update={"anthropic_api_key": None})
    client = LLMClient(no_key, engine)  # constructing is fine
    with pytest.raises(LLMNotConfiguredError):
        client.complete(purpose="smoke", messages=MESSAGES)


def test_sdk_client_built_with_timeout_and_no_sdk_retries(
    settings: Settings, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    def fake_anthropic(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        sdk = MagicMock()
        sdk.messages.create.return_value = fake_message()
        return sdk

    monkeypatch.setattr(client_module.anthropic, "Anthropic", fake_anthropic)
    custom = settings.model_copy(update={"llm_timeout_seconds": 45.0})
    LLMClient(custom, engine).complete(purpose="smoke", messages=MESSAGES)

    assert captured["timeout"] == 45.0
    assert captured["max_retries"] == 0
    assert captured["api_key"] == "sk-test-not-real"


def test_settings_default_timeout_is_120() -> None:
    assert Settings(_env_file=None).llm_timeout_seconds == 120.0
