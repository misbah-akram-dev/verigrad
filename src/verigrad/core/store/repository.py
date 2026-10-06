"""Repository functions. Callers pass a SQLModel `Session`; no other module writes SQL."""

from decimal import Decimal

from sqlalchemy import func
from sqlmodel import Session, select

from verigrad.core.store.models import LLMCall


def record_llm_call(session: Session, call: LLMCall) -> LLMCall:
    session.add(call)
    session.commit()
    session.refresh(call)
    return call


def job_spend(session: Session, job_id: int) -> Decimal:
    """Total actual spend (USD) of every logged Claude call for one job."""
    total = session.exec(
        select(func.coalesce(func.sum(LLMCall.cost_usd), 0.0)).where(LLMCall.job_id == job_id)
    ).one()
    return Decimal(str(total))
