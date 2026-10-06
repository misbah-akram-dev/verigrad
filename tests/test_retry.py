"""Retry logic, using real SDK exception classes built from fake HTTP responses."""

import anthropic
import httpx2
import pytest

from verigrad.core.llm.retry import call_with_retry, is_retryable, retry_after_seconds

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(cls: type[anthropic.APIStatusError], status: int, headers: dict | None = None):  # type: ignore[no-untyped-def]
    response = httpx2.Response(status, headers=headers or {}, request=REQUEST)
    return cls(f"HTTP {status}", response=response, body=None)


class Flaky:
    """Raises each queued exception in turn, then returns 'ok'."""

    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


@pytest.fixture
def sleeps() -> list[float]:
    return []


def test_succeeds_after_rate_limit(sleeps: list[float]) -> None:
    fn = Flaky(status_error(anthropic.RateLimitError, 429, {"retry-after": "3"}))
    assert call_with_retry(fn, sleep=sleeps.append) == "ok"
    assert fn.calls == 2
    assert sleeps == [3.0]


def test_honours_retry_after_ms_over_retry_after(sleeps: list[float]) -> None:
    err = status_error(
        anthropic.RateLimitError, 429, {"retry-after-ms": "1500", "retry-after": "9"}
    )
    call_with_retry(Flaky(err), sleep=sleeps.append)
    assert sleeps == [1.5]


def test_retry_after_is_capped_at_max_delay(sleeps: list[float]) -> None:
    err = status_error(anthropic.RateLimitError, 429, {"retry-after": "600"})
    call_with_retry(Flaky(err), sleep=sleeps.append, max_delay=60)
    assert sleeps == [60]


def test_exponential_backoff_without_header(sleeps: list[float]) -> None:
    errors = [status_error(anthropic.InternalServerError, 500) for _ in range(3)]
    call_with_retry(Flaky(*errors), sleep=sleeps.append, base_delay=1.0, max_delay=60)
    assert len(sleeps) == 3
    # base * 2^attempt plus up to 25% jitter
    for attempt, delay in enumerate(sleeps):
        assert 2**attempt <= delay <= 2**attempt * 1.25


def test_backoff_capped_at_max_delay(sleeps: list[float]) -> None:
    errors = [status_error(anthropic.InternalServerError, 500) for _ in range(4)]
    call_with_retry(Flaky(*errors), sleep=sleeps.append, base_delay=10, max_delay=15)
    assert max(sleeps) <= 15


@pytest.mark.parametrize(
    ("cls", "status"),
    [
        (anthropic.InternalServerError, 500),
        (anthropic.OverloadedError, 529),  # not an InternalServerError subclass in SDK 1.x
        (anthropic.ServiceUnavailableError, 503),
    ],
)
def test_5xx_is_retried(
    cls: type[anthropic.APIStatusError], status: int, sleeps: list[float]
) -> None:
    fn = Flaky(status_error(cls, status))
    assert call_with_retry(fn, sleep=sleeps.append) == "ok"
    assert fn.calls == 2


def test_connection_error_and_timeout_are_retried(sleeps: list[float]) -> None:
    fn = Flaky(anthropic.APIConnectionError(request=REQUEST), anthropic.APITimeoutError(REQUEST))
    assert call_with_retry(fn, sleep=sleeps.append) == "ok"
    assert fn.calls == 3


@pytest.mark.parametrize(
    ("cls", "status"),
    [
        (anthropic.BadRequestError, 400),
        (anthropic.AuthenticationError, 401),
        (anthropic.NotFoundError, 404),
    ],
)
def test_4xx_is_not_retried(
    cls: type[anthropic.APIStatusError], status: int, sleeps: list[float]
) -> None:
    fn = Flaky(status_error(cls, status))
    with pytest.raises(cls):
        call_with_retry(fn, sleep=sleeps.append)
    assert fn.calls == 1
    assert sleeps == []


def test_gives_up_after_max_retries(sleeps: list[float]) -> None:
    errors = [status_error(anthropic.RateLimitError, 429) for _ in range(10)]
    fn = Flaky(*errors)
    with pytest.raises(anthropic.RateLimitError):
        call_with_retry(fn, max_retries=3, sleep=sleeps.append)
    assert fn.calls == 4  # 1 try + 3 retries
    assert len(sleeps) == 3


def test_non_api_errors_propagate_immediately(sleeps: list[float]) -> None:
    fn = Flaky(ValueError("bug"))
    with pytest.raises(ValueError):
        call_with_retry(fn, sleep=sleeps.append)
    assert fn.calls == 1


def test_helpers() -> None:
    assert is_retryable(status_error(anthropic.RateLimitError, 429))
    assert not is_retryable(status_error(anthropic.BadRequestError, 400))
    assert retry_after_seconds(status_error(anthropic.RateLimitError, 429)) is None
    bad = status_error(
        anthropic.RateLimitError, 429, {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}
    )
    assert retry_after_seconds(bad) is None
