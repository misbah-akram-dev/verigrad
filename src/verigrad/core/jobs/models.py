"""Job progress, stored as JSON in `jobs.progress` and rendered by the polling panel."""

from enum import StrEnum

from pydantic import BaseModel, Field


class SourceState(StrEnum):
    QUEUED = "queued"
    FETCHING = "fetching"
    SAVED = "saved"
    REUSED = "reused"
    IMPORTED = "imported"
    BLOCKED = "blocked"
    FAILED = "failed"

    @property
    def done(self) -> bool:
        return self not in (SourceState.QUEUED, SourceState.FETCHING)


class SourceProgress(BaseModel):
    source_id: int
    url: str
    role: str
    state: SourceState = SourceState.QUEUED
    reason: str | None = None
    snapshot_id: int | None = None


class JobProgress(BaseModel):
    sources: list[SourceProgress] = Field(default_factory=list)

    @classmethod
    def parse(cls, raw: str | None) -> "JobProgress":
        return cls.model_validate_json(raw) if raw else cls()
