"""Programme status lifecycle (spec §6). Pure rules, no DB: plain app state, never AI memory.

SAVED ──track──► TARGETING ──apply──► APPLIED ──admit/reject──► ADMITTED / REJECTED
  │                  │                   │  ◄──────undo-result──────┘
  └──drop──► DROPPED ◄──drop──────────────┘ (withdraw)
                └──restore──► TARGETING
"""

from enum import StrEnum

from verigrad.core.store.models import ProgramStatus

MAX_REASON_CHARS = 500
WITHDRAWN = "withdrawn"


class TrackerAction(StrEnum):
    TRACK = "track"
    DROP = "drop"
    RESTORE = "restore"
    APPLY = "apply"
    ADMIT = "admit"
    REJECT = "reject"
    UNDO_RESULT = "undo-result"


TRANSITIONS: dict[ProgramStatus, dict[TrackerAction, ProgramStatus]] = {
    ProgramStatus.SAVED: {
        TrackerAction.TRACK: ProgramStatus.TARGETING,
        TrackerAction.DROP: ProgramStatus.DROPPED,
    },
    ProgramStatus.TARGETING: {
        TrackerAction.APPLY: ProgramStatus.APPLIED,
        TrackerAction.DROP: ProgramStatus.DROPPED,
    },
    ProgramStatus.APPLIED: {
        TrackerAction.ADMIT: ProgramStatus.ADMITTED,
        TrackerAction.REJECT: ProgramStatus.REJECTED,
        TrackerAction.DROP: ProgramStatus.DROPPED,  # withdraw
    },
    ProgramStatus.ADMITTED: {TrackerAction.UNDO_RESULT: ProgramStatus.APPLIED},
    ProgramStatus.REJECTED: {TrackerAction.UNDO_RESULT: ProgramStatus.APPLIED},
    ProgramStatus.DROPPED: {TrackerAction.RESTORE: ProgramStatus.TARGETING},
}


class InvalidTransition(ValueError):
    def __init__(self, current: ProgramStatus, action: TrackerAction) -> None:
        super().__init__(f"can't {action.value} a programme that is {current.value}")
        self.current, self.action = current, action


def next_status(current: ProgramStatus, action: TrackerAction) -> ProgramStatus:
    try:
        return TRANSITIONS[current][action]
    except KeyError:
        raise InvalidTransition(current, action) from None


def allowed_actions(status: ProgramStatus) -> list[TrackerAction]:
    return list(TRANSITIONS[status])


def drop_reason_for(current: ProgramStatus, raw: str | None) -> str | None:
    """Trimmed, capped reason; an empty reason means "withdrawn" when dropping an application."""
    reason = (raw or "").strip()[:MAX_REASON_CHARS]
    if not reason and current == ProgramStatus.APPLIED:
        return WITHDRAWN
    return reason or None


class TrackerFilter(StrEnum):
    TARGETING = "targeting"
    SAVED = "saved"
    APPLIED = "applied"
    DROPPED = "dropped"
    ALL = "all"

    @property
    def statuses(self) -> tuple[ProgramStatus, ...]:
        return _FILTER_STATUSES[self]

    @property
    def label(self) -> str:
        return self.value.capitalize()

    @classmethod
    def parse(cls, raw: str | None) -> "TrackerFilter":
        """Unknown or missing → the default view (Targeting)."""
        try:
            return cls((raw or "").lower())
        except ValueError:
            return cls.TARGETING


_FILTER_STATUSES: dict[TrackerFilter, tuple[ProgramStatus, ...]] = {
    TrackerFilter.TARGETING: (ProgramStatus.TARGETING,),
    TrackerFilter.SAVED: (ProgramStatus.SAVED,),
    # Results are part of "applied": the badge says which.
    TrackerFilter.APPLIED: (ProgramStatus.APPLIED, ProgramStatus.ADMITTED, ProgramStatus.REJECTED),
    TrackerFilter.DROPPED: (ProgramStatus.DROPPED,),
    TrackerFilter.ALL: tuple(ProgramStatus),
}
