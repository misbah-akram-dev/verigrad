"""Extraction schema (spec §4.1).

Two evidence types enforce "Claude proposes, code verifies":
- `ProposedEvidence[T]` is what Claude fills in. It has no confidence field.
- `Evidence[T]` adds `confidence` and `failed_checks`, which only `core/verify/` sets.

To be revised after hand-labelling 5 programmes (v1 step 3).
"""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["html", "json", "pdf"]
Confidence = Literal["high", "medium", "low"]
ApplicantType = Literal["international", "eu", "domestic", "all"]


class ProposedEvidence[T](BaseModel):
    value: T | None = None  # None = not stated on page
    source_quote: str | None = None  # exact text from the source
    source: Source | None = None
    source_ref: str | None = None  # PDF filename/page, JSON path, or element reference


class Evidence[T](ProposedEvidence[T]):
    confidence: Confidence = "low"  # set by code (core/verify), never by Claude
    failed_checks: list[str] = Field(default_factory=list)


# ---- value types -------------------------------------------------------------


class Deadline(BaseModel):
    applicant_type: ApplicantType
    date: dt.date
    time: dt.time | None = None  # None → assume 23:59 local and flag (spec §7)
    timezone: str | None = None  # IANA name, e.g. "Europe/Berlin"
    kind: Literal["fixed", "rolling", "priority", "round"] = "fixed"


class Intake(BaseModel):
    term: Evidence[str]  # e.g. "September 2027"
    deadlines: list[Evidence[Deadline]] = Field(default_factory=list)


class Gpa(BaseModel):
    value: float
    scale: str  # e.g. "4.0", "UK 2:1", "German 1.0–4.0"


class Fee(BaseModel):
    amount: float
    currency: str  # ISO 4217, e.g. "EUR"
    applicant_type: ApplicantType = "all"


# ---- full extraction ---------------------------------------------------------


class ProgramExtraction(BaseModel):
    # Programme
    program_name: Evidence[str] = Field(default_factory=Evidence[str])
    university: Evidence[str] = Field(default_factory=Evidence[str])
    degree_type: Evidence[str] = Field(default_factory=Evidence[str])  # MSc / MA / …
    city: Evidence[str] = Field(default_factory=Evidence[str])
    country: Evidence[str] = Field(default_factory=Evidence[str])
    duration_months: Evidence[int] = Field(default_factory=Evidence[int])
    study_mode: Evidence[Literal["full-time", "part-time", "online"]] = Field(
        default_factory=Evidence[Literal["full-time", "part-time", "online"]]
    )

    # Intakes
    intakes: list[Intake] = Field(default_factory=list)

    # Requirements
    ielts_overall: Evidence[float] = Field(default_factory=Evidence[float])
    ielts_min_band: Evidence[float] = Field(default_factory=Evidence[float])
    toefl_total: Evidence[int] = Field(default_factory=Evidence[int])
    gre_gmat: Evidence[Literal["required", "optional", "not required"]] = Field(
        default_factory=Evidence[Literal["required", "optional", "not required"]]
    )
    min_gpa: Evidence[Gpa] = Field(default_factory=Evidence[Gpa])
    prerequisites: list[Evidence[str]] = Field(default_factory=list)
    required_documents: list[Evidence[str]] = Field(default_factory=list)

    # Fees
    application_fee: list[Evidence[Fee]] = Field(default_factory=list)
    tuition_per_year: list[Evidence[Fee]] = Field(default_factory=list)

    # Meta
    ambiguity_notes: str | None = None
