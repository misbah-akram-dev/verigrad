import datetime as dt

from verigrad.core.extract.schema import (
    Deadline,
    Evidence,
    Fee,
    Intake,
    ProgramExtraction,
    ProposedEvidence,
)


def test_proposed_evidence_has_no_confidence_fields() -> None:
    """Claude's output schema must not let it set its own confidence (spec §5)."""
    fields = set(ProposedEvidence[str].model_fields)
    assert fields == {"value", "source_quote", "source", "source_ref"}
    schema_props = ProposedEvidence[str].model_json_schema()["properties"]
    assert "confidence" not in schema_props
    assert "failed_checks" not in schema_props


def test_evidence_defaults_to_low_with_no_checks() -> None:
    ev = Evidence[int](value=12, source_quote="12 months", source="html")
    assert ev.confidence == "low"
    assert ev.failed_checks == []


def test_none_value_means_not_stated() -> None:
    assert Evidence[str]().value is None


def test_program_extraction_round_trips_through_json() -> None:
    extraction = ProgramExtraction(
        program_name=Evidence[str](value="MSc Data Science", source_quote="MSc Data Science"),
        duration_months=Evidence[int](value=24, source_quote="two years (24 months)"),
        intakes=[
            Intake(
                term=Evidence[str](value="October 2027"),
                deadlines=[
                    Evidence[Deadline](
                        value=Deadline(
                            applicant_type="international",
                            date=dt.date(2027, 1, 15),
                            timezone="Europe/Berlin",
                        ),
                        source_quote="International applicants: 15 January 2027",
                        source="html",
                        confidence="high",
                    )
                ],
            )
        ],
        tuition_per_year=[Evidence[Fee](value=Fee(amount=1500, currency="EUR"))],
        required_documents=[Evidence[str](value="CV"), Evidence[str](value="Transcript")],
    )
    restored = ProgramExtraction.model_validate_json(extraction.model_dump_json())
    assert restored == extraction
    deadline = restored.intakes[0].deadlines[0].value
    assert deadline is not None
    assert deadline.date == dt.date(2027, 1, 15)
    assert deadline.time is None
    assert deadline.kind == "fixed"


def test_empty_extraction_is_valid() -> None:
    empty = ProgramExtraction()
    assert empty.program_name.value is None
    assert empty.intakes == []
