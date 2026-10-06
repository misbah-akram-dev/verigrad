"""Model price table and cost maths. All money is `Decimal` USD."""

import math
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel

PER_MILLION = Decimal(1_000_000)
CACHE_READ_MULTIPLIER = Decimal("0.1")
CACHE_WRITE_MULTIPLIER = Decimal("1.25")
CHARS_PER_TOKEN = 4


class ModelPrice(BaseModel):
    input_per_mtok: Decimal
    output_per_mtok: Decimal


# Anthropic first-party prices, USD per 1M tokens (checked 2026-10-06).
MODEL_PRICES: dict[str, ModelPrice] = {
    "claude-opus-5-5": ModelPrice(input_per_mtok=Decimal("4"), output_per_mtok=Decimal("20")),
    "claude-sonnet-5-5": ModelPrice(input_per_mtok=Decimal("2"), output_per_mtok=Decimal("10")),
    "claude-haiku-4-5": ModelPrice(input_per_mtok=Decimal("1"), output_per_mtok=Decimal("5")),
}


class UnknownModelError(ValueError):
    """Raised for a model with no price entry, so cost is never silently recorded as $0."""

    def __init__(self, model: str) -> None:
        known = ", ".join(sorted(MODEL_PRICES))
        super().__init__(f"No price for model {model!r}. Add it to MODEL_PRICES (known: {known}).")
        self.model = model


class UsageLike(Protocol):
    input_tokens: int
    output_tokens: int


def get_price(model: str) -> ModelPrice:
    try:
        return MODEL_PRICES[model]
    except KeyError:
        raise UnknownModelError(model) from None


def compute_cost(model: str, usage: UsageLike) -> Decimal:
    """Actual cost of one response from its `usage` block (cache tokens included)."""
    price = get_price(model)
    cache_write = getattr(usage, "cache_creation_input_tokens", None) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", None) or 0
    input_cost = (
        Decimal(usage.input_tokens)
        + Decimal(cache_write) * CACHE_WRITE_MULTIPLIER
        + Decimal(cache_read) * CACHE_READ_MULTIPLIER
    ) * price.input_per_mtok
    output_cost = Decimal(usage.output_tokens) * price.output_per_mtok
    return (input_cost + output_cost) / PER_MILLION


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    price = get_price(model)
    return (
        Decimal(input_tokens) * price.input_per_mtok
        + Decimal(output_tokens) * price.output_per_mtok
    ) / PER_MILLION


def estimate_tokens(text: str) -> int:
    """Rough local token estimate (chars / 4, rounded up). Accuracy is measured via
    `llm_calls.estimated_cost_usd` vs `cost_usd`."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)
