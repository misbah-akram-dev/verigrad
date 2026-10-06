"""SQLModel tables (spec §4.2).

List/JSON-valued columns are stored as JSON text. Re-extraction adds new `extractions`
rows; history is never overwritten.
"""

from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class ProgramStatus(StrEnum):
    SAVED = "SAVED"
    TARGETING = "TARGETING"
    APPLIED = "APPLIED"
    ADMITTED = "ADMITTED"
    REJECTED = "REJECTED"
    DROPPED = "DROPPED"


class FetchOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    BLOCKED = "BLOCKED"
    MANUAL_IMPORT = "MANUAL_IMPORT"
    FAILED = "FAILED"


class JobKind(StrEnum):
    FETCH = "fetch"
    EXTRACT = "extract"
    EVAL = "eval"
    RECHECK = "recheck"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    OVER_BUDGET = "over_budget"


class Program(SQLModel, table=True):
    __tablename__ = "programs"

    id: int | None = Field(default=None, primary_key=True)
    url: str = Field(index=True)
    name: str | None = None
    university: str | None = None
    status: ProgramStatus = Field(default=ProgramStatus.SAVED, index=True)
    status_changed_at: datetime = Field(default_factory=utcnow)
    drop_reason: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Snapshot(SQLModel, table=True):
    __tablename__ = "snapshots"

    id: int | None = Field(default=None, primary_key=True)
    program_id: int = Field(foreign_key="programs.id", index=True)
    fetched_at: datetime = Field(default_factory=utcnow)
    fetch_outcome: FetchOutcome
    html_path: str | None = None
    text_path: str | None = None
    screenshot_path: str | None = None
    json_paths: str = "[]"  # JSON list of paths
    pdf_paths: str = "[]"  # JSON list of paths
    visibility_map_path: str | None = None
    content_hash: str | None = Field(default=None, index=True)
    imported_manually: bool = False


class Extraction(SQLModel, table=True):
    __tablename__ = "extractions"

    id: int | None = Field(default=None, primary_key=True)
    snapshot_id: int = Field(foreign_key="snapshots.id", index=True)
    field_path: str = Field(index=True)  # e.g. "intakes[0].deadlines[1]"
    value_json: str  # JSON-encoded value (may be "null")
    source_quote: str | None = None
    source: str | None = None  # html | json | pdf
    source_ref: str | None = None
    confidence: str  # high | medium | low — set by core/verify, never by Claude
    failed_checks: str = "[]"  # JSON list of check names
    user_confirmed: bool = False
    model: str
    prompt_version: str
    created_at: datetime = Field(default_factory=utcnow)


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: int | None = Field(default=None, primary_key=True)
    program_id: int = Field(foreign_key="programs.id", index=True)
    title: str
    due_date_pkt: datetime
    lead_time_days: int
    done: bool = False


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: int | None = Field(default=None, primary_key=True)
    kind: JobKind
    program_id: int | None = Field(default=None, foreign_key="programs.id", index=True)
    status: JobStatus = Field(default=JobStatus.QUEUED, index=True)
    progress: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class LLMCall(SQLModel, table=True):
    """One row per successful Claude call. The cost guard is scoped per `job_id`."""

    __tablename__ = "llm_calls"

    id: int | None = Field(default=None, primary_key=True)
    purpose: str = Field(index=True)  # extract | eval | spider | label | smoke
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: float
    estimated_cost_usd: float
    latency_ms: int
    request_id: str | None = None
    job_id: int | None = Field(default=None, foreign_key="jobs.id", index=True)
    program_id: int | None = Field(default=None, foreign_key="programs.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class EvalRun(SQLModel, table=True):
    __tablename__ = "eval_runs"

    id: int | None = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=utcnow)
    model: str
    prompt_version: str
    accuracy: float | None = None
    calibration_json: str = "{}"
    cost_usd: float = 0.0
    report_path: str | None = None
