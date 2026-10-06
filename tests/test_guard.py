from decimal import Decimal

import pytest

from verigrad.core.llm.guard import BudgetExceededError, check_budget

BUDGET = Decimal("0.30")


def test_under_budget_passes() -> None:
    check_budget(job_id=1, spent=Decimal("0.10"), estimate=Decimal("0.05"), budget=BUDGET)


def test_exactly_at_budget_passes() -> None:
    check_budget(job_id=1, spent=Decimal("0.20"), estimate=Decimal("0.10"), budget=BUDGET)


def test_over_budget_raises_with_numbers() -> None:
    with pytest.raises(BudgetExceededError) as info:
        check_budget(job_id=7, spent=Decimal("0.25"), estimate=Decimal("0.06"), budget=BUDGET)
    err = info.value
    assert err.job_id == 7
    assert err.spent == Decimal("0.25")
    assert err.estimate == Decimal("0.06")
    assert err.budget == BUDGET
    assert "Job 7" in str(err)


def test_estimate_alone_can_exceed_budget() -> None:
    with pytest.raises(BudgetExceededError):
        check_budget(job_id=1, spent=Decimal("0"), estimate=Decimal("0.31"), budget=BUDGET)
