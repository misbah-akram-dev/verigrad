"""Per-job cost guard: block a call that would push a job over its budget."""

from decimal import Decimal


class BudgetExceededError(RuntimeError):
    def __init__(self, *, job_id: int, spent: Decimal, estimate: Decimal, budget: Decimal) -> None:
        super().__init__(
            f"Job {job_id}: spent ${spent:.4f} + estimated ${estimate:.4f} "
            f"would exceed budget ${budget:.4f}"
        )
        self.job_id = job_id
        self.spent = spent
        self.estimate = estimate
        self.budget = budget


def check_budget(*, job_id: int, spent: Decimal, estimate: Decimal, budget: Decimal) -> None:
    """Raise `BudgetExceededError` if `spent + estimate > budget`. Exactly at budget is allowed."""
    if spent + estimate > budget:
        raise BudgetExceededError(job_id=job_id, spent=spent, estimate=estimate, budget=budget)
