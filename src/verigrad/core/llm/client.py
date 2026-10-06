"""The single entry point for Claude calls: retries, budget guard, cost/latency logging."""

import json
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Literal, get_args

import anthropic
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine
from sqlmodel import Session

from verigrad.config import Settings
from verigrad.core.llm.guard import check_budget
from verigrad.core.llm.pricing import compute_cost, estimate_cost, estimate_tokens, get_price
from verigrad.core.llm.retry import call_with_retry
from verigrad.core.store.models import LLMCall
from verigrad.core.store.repository import job_spend, record_llm_call

Purpose = Literal["extract", "eval", "spider", "label", "smoke"]
PURPOSES: frozenset[str] = frozenset(get_args(Purpose))


class LLMNotConfiguredError(RuntimeError):
    """Raised when a Claude call is attempted without ANTHROPIC_API_KEY."""


class LLMResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    message: Any  # anthropic.types.Message
    model: str
    cost_usd: Decimal
    estimated_cost_usd: Decimal
    latency_ms: int
    request_id: str | None
    llm_call_id: int
    over_budget: bool = False


def _round_usd(value: Decimal) -> float:
    return float(round(value, 6))


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        sdk_client: Any | None = None,
        *,
        max_retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._sdk_client = sdk_client
        self._max_retries = max_retries
        self._sleep = sleep

    @property
    def sdk(self) -> Any:
        """The Anthropic SDK client, created on first use (the app runs without a key)."""
        if self._sdk_client is None:
            key = self._settings.anthropic_api_key
            if key is None:
                raise LLMNotConfiguredError("ANTHROPIC_API_KEY is not set; add it to .env.")
            self._sdk_client = anthropic.Anthropic(
                api_key=key.get_secret_value(),
                max_retries=0,  # retries are handled by core/llm/retry.py
                timeout=self._settings.llm_timeout_seconds,
            )
        return self._sdk_client

    def complete(
        self,
        *,
        purpose: Purpose,
        messages: list[dict[str, Any]],
        system: str | list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 16000,
        job_id: int | None = None,
        program_id: int | None = None,
        expected_output_tokens: int = 4000,
        **kwargs: Any,
    ) -> LLMResult:
        if purpose not in PURPOSES:
            raise ValueError(f"Unknown purpose {purpose!r}; expected one of {sorted(PURPOSES)}")
        model = model or self._settings.extract_model
        get_price(model)  # fail fast on an unpriced model, before any network call

        prompt_text = json.dumps({"system": system, "messages": messages}, default=str)
        estimate = estimate_cost(model, estimate_tokens(prompt_text), expected_output_tokens)
        budget = Decimal(str(self._settings.max_cost_per_job))

        if job_id is not None:
            with Session(self._engine) as session:
                spent = job_spend(session, job_id)
            check_budget(job_id=job_id, spent=spent, estimate=estimate, budget=budget)

        request: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if system is not None:
            request["system"] = system
        request.update(kwargs)

        sdk = self.sdk
        started = time.perf_counter()
        response = call_with_retry(
            lambda: sdk.messages.create(**request),
            max_retries=self._max_retries,
            sleep=self._sleep,
        )
        latency_ms = round((time.perf_counter() - started) * 1000)

        usage = response.usage
        cost = compute_cost(model, usage)
        request_id = getattr(response, "_request_id", None)
        row = LLMCall(
            purpose=purpose,
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", None) or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", None) or 0,
            cost_usd=_round_usd(cost),
            estimated_cost_usd=_round_usd(estimate),
            latency_ms=latency_ms,
            request_id=request_id,
            job_id=job_id,
            program_id=program_id,
        )
        with Session(self._engine) as session:
            row = record_llm_call(session, row)
            over_budget = job_id is not None and job_spend(session, job_id) > budget

        assert row.id is not None
        return LLMResult(
            message=response,
            model=model,
            cost_usd=cost,
            estimated_cost_usd=estimate,
            latency_ms=latency_ms,
            request_id=request_id,
            llm_call_id=row.id,
            over_budget=over_budget,
        )
