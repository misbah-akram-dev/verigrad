"""Status lifecycle rules (spec §6): the full status × action matrix, reasons and filters."""

import pytest

from verigrad.core.store.models import ProgramStatus as S
from verigrad.core.tracker.status import (
    MAX_REASON_CHARS,
    WITHDRAWN,
    InvalidTransition,
    TrackerAction,
    TrackerFilter,
    allowed_actions,
    drop_reason_for,
    next_status,
)

A = TrackerAction

VALID: dict[tuple[S, TrackerAction], S] = {
    (S.SAVED, A.TRACK): S.TARGETING,
    (S.SAVED, A.DROP): S.DROPPED,
    (S.TARGETING, A.APPLY): S.APPLIED,
    (S.TARGETING, A.DROP): S.DROPPED,
    (S.APPLIED, A.ADMIT): S.ADMITTED,
    (S.APPLIED, A.REJECT): S.REJECTED,
    (S.APPLIED, A.DROP): S.DROPPED,  # withdraw
    (S.ADMITTED, A.UNDO_RESULT): S.APPLIED,
    (S.REJECTED, A.UNDO_RESULT): S.APPLIED,
    (S.DROPPED, A.RESTORE): S.TARGETING,
}
ALL_PAIRS = [(status, action) for status in S for action in A]


@pytest.mark.parametrize(("status", "action"), ALL_PAIRS)
def test_transition_matrix(status: S, action: TrackerAction) -> None:
    if (status, action) in VALID:
        assert next_status(status, action) == VALID[(status, action)]
    else:
        with pytest.raises(InvalidTransition):
            next_status(status, action)


@pytest.mark.parametrize("status", list(S))
def test_allowed_actions_match_the_matrix(status: S) -> None:
    expected = {action for (s, action) in VALID if s == status}
    assert set(allowed_actions(status)) == expected


def test_restore_always_goes_to_targeting_even_after_withdrawing() -> None:
    dropped = next_status(S.APPLIED, A.DROP)
    assert next_status(dropped, A.RESTORE) == S.TARGETING


def test_invalid_transition_message() -> None:
    with pytest.raises(InvalidTransition, match="can't restore a programme that is SAVED"):
        next_status(S.SAVED, A.RESTORE)


@pytest.mark.parametrize(
    ("current", "raw", "expected"),
    [
        (S.SAVED, None, None),
        (S.TARGETING, "   ", None),
        (S.TARGETING, "  too expensive  ", "too expensive"),
        (S.APPLIED, "", WITHDRAWN),
        (S.APPLIED, None, WITHDRAWN),
        (S.APPLIED, "got a better offer", "got a better offer"),
    ],
)
def test_drop_reason(current: S, raw: str | None, expected: str | None) -> None:
    assert drop_reason_for(current, raw) == expected


def test_drop_reason_is_capped() -> None:
    reason = drop_reason_for(S.SAVED, "x" * (MAX_REASON_CHARS + 50))
    assert reason is not None and len(reason) == MAX_REASON_CHARS


def test_filters() -> None:
    assert TrackerFilter.TARGETING.statuses == (S.TARGETING,)
    assert TrackerFilter.SAVED.statuses == (S.SAVED,)
    assert set(TrackerFilter.APPLIED.statuses) == {S.APPLIED, S.ADMITTED, S.REJECTED}
    assert TrackerFilter.DROPPED.statuses == (S.DROPPED,)
    assert set(TrackerFilter.ALL.statuses) == set(S)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, TrackerFilter.TARGETING),
        ("", TrackerFilter.TARGETING),
        ("bogus", TrackerFilter.TARGETING),
        ("Dropped", TrackerFilter.DROPPED),
        ("all", TrackerFilter.ALL),
    ],
)
def test_filter_parse(raw: str | None, expected: TrackerFilter) -> None:
    assert TrackerFilter.parse(raw) == expected
