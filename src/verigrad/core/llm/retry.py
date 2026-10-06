"""Retries with exponential backoff that honour the server's retry headers.

The SDK client is built with `max_retries=0`, so this is the only retry layer.
"""

import logging
import random
import time
from collections.abc import Callable

import anthropic

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 409, 429}


def is_retryable(exc: BaseException) -> bool:
    """429, 408, 409 and every 5xx (incl. 529 overloaded) plus connection errors/timeouts."""
    if isinstance(exc, anthropic.APIConnectionError):  # includes APITimeoutError
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in RETRYABLE_STATUS or exc.status_code >= 500
    return False


def retry_after_seconds(exc: BaseException) -> float | None:
    """Delay requested by the server via `retry-after-ms` or `retry-after` (seconds)."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = response.headers
    for name, scale in (("retry-after-ms", 1000.0), ("retry-after", 1.0)):
        raw = headers.get(name)
        if raw is None:
            continue
        try:
            value = float(raw) / scale
        except ValueError:
            continue  # e.g. an HTTP-date; fall back to backoff
        if value >= 0:
            return value
    return None


def backoff_delay(attempt: int, *, base_delay: float, max_delay: float) -> float:
    """`base * 2^attempt` with up to 25% jitter, capped at `max_delay`."""
    delay = base_delay * (2**attempt)
    return min(max_delay, delay * (1 + random.uniform(0, 0.25)))


def call_with_retry[T](
    fn: Callable[[], T],
    *,
    max_retries: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call `fn`, retrying retryable API errors up to `max_retries` times."""
    attempt = 0
    while True:
        try:
            return fn()
        except anthropic.APIError as exc:
            if not is_retryable(exc) or attempt >= max_retries:
                raise
            requested = retry_after_seconds(exc)
            delay = (
                min(requested, max_delay)
                if requested is not None
                else backoff_delay(attempt, base_delay=base_delay, max_delay=max_delay)
            )
            logger.warning(
                "Claude call failed (%s); retry %d/%d in %.2fs",
                type(exc).__name__,
                attempt + 1,
                max_retries,
                delay,
            )
            sleep(delay)
            attempt += 1
