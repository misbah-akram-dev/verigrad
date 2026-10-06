"""Optional live smoke test. Excluded from `make test`; run with `make test-live`.

Costs a fraction of a cent. Skipped when ANTHROPIC_API_KEY is empty.
"""

import pytest
from sqlmodel import Session, select

from verigrad.config import Settings
from verigrad.core.llm import LLMClient
from verigrad.core.store.db import init_db, make_engine
from verigrad.core.store.models import LLMCall

pytestmark = pytest.mark.live


def test_real_call_is_logged_with_cost(tmp_path) -> None:  # type: ignore[no-untyped-def]
    real = Settings()  # reads .env / environment
    if not real.has_api_key:
        pytest.skip("ANTHROPIC_API_KEY is empty")

    engine = make_engine(f"sqlite:///{tmp_path / 'live.db'}")
    init_db(engine)
    client = LLMClient(real, engine)

    result = client.complete(
        purpose="smoke",
        messages=[{"role": "user", "content": "Reply with the single word: pong"}],
        max_tokens=1024,
        expected_output_tokens=64,
    )

    assert result.cost_usd > 0
    assert result.request_id
    with Session(engine) as session:
        row = session.exec(select(LLMCall)).one()
    assert row.purpose == "smoke"
    assert row.cost_usd > 0
    assert row.request_id == result.request_id
