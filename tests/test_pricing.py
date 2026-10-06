from decimal import Decimal
from types import SimpleNamespace

import pytest

from verigrad.core.llm.pricing import (
    MODEL_PRICES,
    UnknownModelError,
    compute_cost,
    estimate_cost,
    estimate_tokens,
)


def usage(inp: int, out: int, cache_write: int | None = None, cache_read: int | None = None):  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_creation_input_tokens=cache_write,
        cache_read_input_tokens=cache_read,
    )


def test_price_table_has_exactly_the_agreed_models() -> None:
    assert set(MODEL_PRICES) == {"claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5"}


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        # 1M input + 1M output = input price + output price
        ("claude-opus-5-5", Decimal("24")),
        ("claude-sonnet-5-5", Decimal("12")),
        ("claude-haiku-4-5", Decimal("6")),
    ],
)
def test_compute_cost_per_million(model: str, expected: Decimal) -> None:
    assert compute_cost(model, usage(1_000_000, 1_000_000)) == expected


def test_compute_cost_typical_extraction_call() -> None:
    # Sonnet 5.5: 20k in × $2/M = $0.04; 3k out × $10/M = $0.03
    assert compute_cost("claude-sonnet-5-5", usage(20_000, 3_000)) == Decimal("0.07")


def test_compute_cost_includes_cache_tokens() -> None:
    # Sonnet: 1M cache write × 1.25 × $2 = $2.50; 1M cache read × 0.1 × $2 = $0.20
    cost = compute_cost(
        "claude-sonnet-5-5", usage(0, 0, cache_write=1_000_000, cache_read=1_000_000)
    )
    assert cost == Decimal("2.7")


def test_compute_cost_treats_missing_cache_fields_as_zero() -> None:
    bare = SimpleNamespace(input_tokens=1_000_000, output_tokens=0)
    assert compute_cost("claude-haiku-4-5", bare) == Decimal("1")


def test_unknown_model_raises_instead_of_zero_cost() -> None:
    with pytest.raises(UnknownModelError, match="claude-fable-5-1"):
        compute_cost("claude-fable-5-1", usage(10, 10))
    with pytest.raises(UnknownModelError):
        estimate_cost("gpt-4o", 10, 10)


def test_estimate_cost() -> None:
    # Haiku: 4000 in × $1/M + 4000 out × $5/M = $0.004 + $0.02
    assert estimate_cost("claude-haiku-4-5", 4000, 4000) == Decimal("0.024")


@pytest.mark.parametrize(("text", "tokens"), [("", 0), ("abc", 1), ("abcd", 1), ("abcde", 2)])
def test_estimate_tokens_rounds_up(text: str, tokens: int) -> None:
    assert estimate_tokens(text) == tokens
