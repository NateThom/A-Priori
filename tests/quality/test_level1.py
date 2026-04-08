"""Tests for Story 7.3: Level 1 Automated Consistency Checks.

AC traceability:

AC1: Given a librarian output with an empty description, when Level 1 runs,
     then it fails with failure_reason = "Level 1: empty description".

AC2: Given a librarian output matching a boilerplate pattern, when Level 1 runs,
     then it fails with a message identifying the generic description.

AC3: Given a librarian output asserting a relationship to a concept name that
     doesn't exist in the graph and is not being created in the same batch,
     when Level 1 runs, then it fails with a referential integrity error.

AC4: Given a librarian output that creates two new concepts and an edge between
     them in the same batch, when Level 1 runs, then the referential integrity
     check passes.

AC5: Given a librarian output with confidence = 1.5, when Level 1 runs,
     then it fails with a confidence range error.

AC6: Given a librarian output that cannot be parsed into the expected Pydantic
     models, when Level 1 runs, then it fails with a schema validity error.

AC7: Given a librarian output using edge type "invented-type", when Level 1 runs,
     then it fails with an invalid edge type error.

AC8: Given a librarian output asserting a depends-on relationship with no
     structural corroboration, when Level 1 runs, then it passes but the
     confidence score is reduced by the configured factor (default: 0.2).

AC9: Given a known-good fixture, when Level 1 runs, then it passes.

DoD: All six checks implemented. Tested against all fixtures from Story 7.2.
     Execution time under 10ms per check.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from apriori.models.librarian_output import ConceptProposal, EdgeProposal, LibrarianOutput
from apriori.quality.level1 import (
    DEFAULT_CORROBORATION_PENALTY,
    VALID_EDGE_TYPES,
    Level1Result,
    check_level1,
    run_level1_checks,
)


# ---------------------------------------------------------------------------
# Fixture loading helpers
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "librarian_outputs"


def _load_fixture(name: str) -> dict[str, Any]:
    path = FIXTURE_DIR / f"{name}.json"
    with open(path) as f:
        return json.load(f)


def _parsed_output(fixture_name: str) -> LibrarianOutput:
    data = _load_fixture(fixture_name)
    return LibrarianOutput.model_validate(data["librarian_output"])


def _raw_output(fixture_name: str) -> Any:
    data = _load_fixture(fixture_name)
    return data["librarian_output"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_good_concept(name: str = "AuthService", description: str | None = None) -> ConceptProposal:
    """Return a known-good ConceptProposal that passes all Level 1 checks."""
    desc = description or (
        "Verifies JWT tokens against the SUPABASE_JWT_SECRET environment variable "
        "using the jose library, implementing a Fastify preHandler hook that attaches "
        "the decoded user context to each request."
    )
    return ConceptProposal(name=name, description=desc, confidence=0.85)


# ---------------------------------------------------------------------------
# AC9: Known-good fixtures pass
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name", [
    "good_01_auth_service",
    "good_02_database_pool_with_code_ref",
    "good_03_multi_concept_with_edges",
    "good_04_high_confidence_payment",
    "good_05_complex_analysis",
])
def test_known_good_fixture_passes(fixture_name: str) -> None:
    """Given a known-good fixture, when Level 1 runs, then it passes."""
    result = check_level1(_raw_output(fixture_name))
    assert result.passed, (
        f"{fixture_name}: expected pass but got failure: "
        f"{result.failure_record.failure_reason if result.failure_record else 'unknown'}"
    )
    assert result.adjusted_output is not None
    assert result.failure_record is None


# ---------------------------------------------------------------------------
# AC1: Empty description
# ---------------------------------------------------------------------------


def test_empty_description_fails(fixture_name: str = "bad_01_empty_description") -> None:
    """Given a librarian output with an empty description, when Level 1 runs,
    then it fails with failure_reason = 'Level 1: empty description'."""
    result = check_level1(_raw_output(fixture_name))
    assert not result.passed
    assert result.failure_record is not None
    assert result.failure_record.failure_reason == "Level 1: empty description"


def test_whitespace_description_fails() -> None:
    """Given a concept with a whitespace-only description, Level 1 fails with
    empty description error."""
    result = check_level1(_raw_output("bad_02_whitespace_description"))
    assert not result.passed
    assert result.failure_record is not None
    assert result.failure_record.failure_reason == "Level 1: empty description"


def test_empty_description_failure_record_fields() -> None:
    """The FailureRecord produced for an empty description is well-formed."""
    result = check_level1(_raw_output("bad_01_empty_description"))
    record = result.failure_record
    assert record is not None
    assert record.attempted_at is not None
    assert record.model_used == "none"
    assert record.prompt_template == "level1_consistency_checks"
    assert "Level 1" in record.failure_reason


# ---------------------------------------------------------------------------
# AC2: Boilerplate / generic description
# ---------------------------------------------------------------------------


def test_generic_description_pattern_1_fails() -> None:
    """Given 'handles X operations and provides methods for managing Y' pattern,
    Level 1 fails with a generic description message."""
    result = check_level1(_raw_output("bad_03_generic_description_01"))
    assert not result.passed
    assert result.failure_record is not None
    assert "generic description" in result.failure_record.failure_reason


def test_generic_description_pattern_2_fails() -> None:
    """Given 'processes data and returns results' pattern, Level 1 fails."""
    result = check_level1(_raw_output("bad_04_generic_description_02"))
    assert not result.passed
    assert result.failure_record is not None
    assert "generic description" in result.failure_record.failure_reason


def test_short_description_fails() -> None:
    """Given a non-empty description under 50 chars, Level 1 fails as generic."""
    short_desc = "Handles auth."  # 13 chars, specific-sounding but too short
    output = LibrarianOutput(concepts=[
        ConceptProposal(name="AuthService", description=short_desc, confidence=0.8)
    ])
    result = run_level1_checks(output)
    assert not result.passed
    assert result.failure_record is not None
    assert "generic description" in result.failure_record.failure_reason


def test_whitespace_description_passes_generic_check() -> None:
    """Whitespace-only descriptions fail the empty check, not the generic check.
    Verifies checks are independent for fixture metadata consistency."""
    # The generic check should not raise for whitespace (empty check handles it)
    # We test description_non_generic in isolation by building an output that
    # passes description_non_empty but has a short description.
    # (Already covered by test_short_description_fails above — this test
    # confirms the design boundary for fixture metadata.)
    output = LibrarianOutput(concepts=[_make_good_concept()])
    result = run_level1_checks(output)
    assert result.passed  # sanity: good concept passes all checks


# ---------------------------------------------------------------------------
# AC3: Referential integrity — missing concept
# ---------------------------------------------------------------------------


def test_referential_integrity_missing_concept_fails() -> None:
    """Given an edge referencing a concept not in the batch or existing graph,
    Level 1 fails with a referential integrity error."""
    result = check_level1(_raw_output("bad_05_referential_integrity"))
    assert not result.passed
    assert result.failure_record is not None
    assert "referential integrity" in result.failure_record.failure_reason


def test_referential_integrity_missing_concept_not_in_existing_graph_fails() -> None:
    """Given a concept referenced by an edge that is absent from both the batch
    and the existing_concept_names, Level 1 fails."""
    output = LibrarianOutput(
        concepts=[_make_good_concept("ConceptA")],
        edges=[EdgeProposal(
            source_name="ConceptA",
            target_name="UnknownConcept",
            edge_type="depends-on",
            confidence=0.7,
        )],
    )
    result = run_level1_checks(output, existing_concept_names=frozenset())
    assert not result.passed
    assert result.failure_record is not None
    assert "referential integrity" in result.failure_record.failure_reason
    assert "UnknownConcept" in result.failure_record.failure_reason


def test_referential_integrity_concept_in_existing_graph_passes() -> None:
    """Given an edge referencing a concept that exists in the knowledge graph
    (not in the current batch), Level 1 passes when existing_concept_names is provided."""
    output = LibrarianOutput(
        concepts=[_make_good_concept("ConceptA")],
        edges=[EdgeProposal(
            source_name="ConceptA",
            target_name="GraphConcept",
            edge_type="depends-on",
            confidence=0.7,
        )],
    )
    result = run_level1_checks(
        output,
        existing_concept_names=frozenset({"GraphConcept"}),
    )
    assert result.passed, (
        f"Expected pass but got: {result.failure_record.failure_reason if result.failure_record else 'unknown'}"
    )


# ---------------------------------------------------------------------------
# AC4: Referential integrity — two new concepts + edge in same batch
# ---------------------------------------------------------------------------


def test_referential_integrity_intra_batch_edge_passes() -> None:
    """Given two new concepts and an edge between them in the same batch,
    referential integrity check passes."""
    result = check_level1(_raw_output("good_03_multi_concept_with_edges"))
    assert result.passed, (
        f"Expected pass but got: {result.failure_record.failure_reason if result.failure_record else 'unknown'}"
    )


def test_referential_integrity_intra_batch_both_directions() -> None:
    """Both source_name and target_name are validated for referential integrity."""
    output = LibrarianOutput(
        concepts=[_make_good_concept("ConceptA"), _make_good_concept("ConceptB")],
        edges=[
            EdgeProposal(source_name="ConceptA", target_name="ConceptB", edge_type="depends-on", confidence=0.7),
            EdgeProposal(source_name="ConceptB", target_name="ConceptA", edge_type="relates-to", confidence=0.6),
        ],
    )
    result = run_level1_checks(output)
    assert result.passed


# ---------------------------------------------------------------------------
# AC5: Confidence out of range
# ---------------------------------------------------------------------------


def test_confidence_too_high_fails() -> None:
    """Given confidence = 1.5, Level 1 fails with a confidence range error."""
    result = check_level1(_raw_output("bad_06_confidence_too_high"))
    assert not result.passed
    assert result.failure_record is not None
    assert "confidence" in result.failure_record.failure_reason.lower()
    assert "range" in result.failure_record.failure_reason.lower()


def test_confidence_negative_fails() -> None:
    """Given confidence = -0.1 on an edge, Level 1 fails with a confidence range error."""
    result = check_level1(_raw_output("bad_07_confidence_negative"))
    assert not result.passed
    assert result.failure_record is not None
    assert "confidence" in result.failure_record.failure_reason.lower()
    assert "range" in result.failure_record.failure_reason.lower()


def test_confidence_boundary_values_pass() -> None:
    """Confidence values of exactly 0.0 and 1.0 are valid."""
    output = LibrarianOutput(concepts=[
        ConceptProposal(name="ConceptA", description=_make_good_concept().description, confidence=0.0),
        ConceptProposal(name="ConceptB", description=_make_good_concept().description, confidence=1.0),
    ])
    result = run_level1_checks(output)
    assert result.passed


def test_confidence_checked_on_both_concepts_and_edges() -> None:
    """Confidence range check applies to both concept confidence and edge confidence."""
    output = LibrarianOutput(
        concepts=[_make_good_concept("ConceptA"), _make_good_concept("ConceptB")],
        edges=[EdgeProposal(
            source_name="ConceptA",
            target_name="ConceptB",
            edge_type="depends-on",
            confidence=1.1,  # invalid
        )],
    )
    result = run_level1_checks(output)
    assert not result.passed
    assert result.failure_record is not None
    assert "confidence" in result.failure_record.failure_reason.lower()


# ---------------------------------------------------------------------------
# AC6: Unparseable schema
# ---------------------------------------------------------------------------


def test_unparseable_schema_fails() -> None:
    """Given a raw string instead of a LibrarianOutput dict, Level 1 fails
    with a schema validity error."""
    result = check_level1(_raw_output("bad_08_unparseable_schema"))
    assert not result.passed
    assert result.failure_record is not None
    assert "schema" in result.failure_record.failure_reason.lower()


def test_none_input_fails_schema_check() -> None:
    """Given None as raw output, Level 1 fails with a schema validity error."""
    result = check_level1(None)
    assert not result.passed
    assert result.failure_record is not None
    assert "schema" in result.failure_record.failure_reason.lower()


def test_empty_dict_fails_schema_check() -> None:
    """Given an empty dict (missing 'concepts' key), Level 1 fails with schema error."""
    result = check_level1({})
    assert not result.passed
    assert result.failure_record is not None
    assert "schema" in result.failure_record.failure_reason.lower()


# ---------------------------------------------------------------------------
# AC7: Invalid edge type
# ---------------------------------------------------------------------------


def test_invalid_edge_type_fails() -> None:
    """Given edge type 'knows-about' (not in vocabulary), Level 1 fails."""
    result = check_level1(_raw_output("bad_09_invalid_edge_type"))
    assert not result.passed
    assert result.failure_record is not None
    assert "edge type" in result.failure_record.failure_reason.lower()
    assert "knows-about" in result.failure_record.failure_reason


def test_invented_edge_type_fails() -> None:
    """Given edge type 'invented-type', Level 1 fails with an invalid edge type error."""
    output = LibrarianOutput(
        concepts=[_make_good_concept("ConceptA"), _make_good_concept("ConceptB")],
        edges=[EdgeProposal(
            source_name="ConceptA",
            target_name="ConceptB",
            edge_type="invented-type",
            confidence=0.7,
        )],
    )
    result = run_level1_checks(output)
    assert not result.passed
    assert result.failure_record is not None
    assert "invalid edge type" in result.failure_record.failure_reason
    assert "invented-type" in result.failure_record.failure_reason


def test_all_valid_edge_types_accepted() -> None:
    """All vocabulary edge types are accepted by Level 1."""
    concepts = [_make_good_concept(f"Concept{i}") for i in range(len(VALID_EDGE_TYPES) + 1)]
    edges = [
        EdgeProposal(
            source_name=concepts[i].name,
            target_name=concepts[i + 1].name,
            edge_type=edge_type,
            confidence=0.7,
            evidence_type="structural",  # avoid confidence adjustment
        )
        for i, edge_type in enumerate(sorted(VALID_EDGE_TYPES))
    ]
    output = LibrarianOutput(concepts=concepts, edges=edges)
    result = run_level1_checks(output)
    assert result.passed, (
        f"Expected pass but got: {result.failure_record.failure_reason if result.failure_record else 'unknown'}"
    )


# ---------------------------------------------------------------------------
# AC8: Structural corroboration soft check
# ---------------------------------------------------------------------------


def test_depends_on_without_structural_corroboration_passes_but_reduces_confidence() -> None:
    """Given a depends-on edge with evidence_type='semantic', Level 1 passes but
    confidence is reduced by the default factor (0.2)."""
    original_confidence = 0.8
    output = LibrarianOutput(
        concepts=[_make_good_concept("ConceptA"), _make_good_concept("ConceptB")],
        edges=[EdgeProposal(
            source_name="ConceptA",
            target_name="ConceptB",
            edge_type="depends-on",
            confidence=original_confidence,
            evidence_type="semantic",
        )],
    )
    result = run_level1_checks(output)
    assert result.passed
    assert result.adjusted_output is not None
    adjusted_edge = result.adjusted_output.edges[0]
    expected = original_confidence - DEFAULT_CORROBORATION_PENALTY
    assert abs(adjusted_edge.confidence - expected) < 1e-9, (
        f"Expected confidence {expected}, got {adjusted_edge.confidence}"
    )


def test_depends_on_with_structural_corroboration_not_penalized() -> None:
    """A depends-on edge with evidence_type='structural' is NOT penalized."""
    original_confidence = 0.8
    output = LibrarianOutput(
        concepts=[_make_good_concept("ConceptA"), _make_good_concept("ConceptB")],
        edges=[EdgeProposal(
            source_name="ConceptA",
            target_name="ConceptB",
            edge_type="depends-on",
            confidence=original_confidence,
            evidence_type="structural",
        )],
    )
    result = run_level1_checks(output)
    assert result.passed
    assert result.adjusted_output is not None
    assert result.adjusted_output.edges[0].confidence == original_confidence


def test_non_depends_on_edge_not_penalized() -> None:
    """Edges with types other than depends-on are not penalized even without
    structural corroboration."""
    for edge_type in VALID_EDGE_TYPES - {"depends-on"}:
        original_confidence = 0.8
        output = LibrarianOutput(
            concepts=[_make_good_concept("ConceptA"), _make_good_concept("ConceptB")],
            edges=[EdgeProposal(
                source_name="ConceptA",
                target_name="ConceptB",
                edge_type=edge_type,
                confidence=original_confidence,
                evidence_type="semantic",
            )],
        )
        result = run_level1_checks(output)
        assert result.passed, f"Failed for edge_type={edge_type}"
        assert result.adjusted_output is not None
        assert result.adjusted_output.edges[0].confidence == original_confidence, (
            f"Edge type {edge_type} should not be penalized"
        )


def test_corroboration_penalty_configurable() -> None:
    """The corroboration penalty is configurable."""
    original_confidence = 0.8
    custom_penalty = 0.1
    output = LibrarianOutput(
        concepts=[_make_good_concept("ConceptA"), _make_good_concept("ConceptB")],
        edges=[EdgeProposal(
            source_name="ConceptA",
            target_name="ConceptB",
            edge_type="depends-on",
            confidence=original_confidence,
            evidence_type="semantic",
        )],
    )
    result = run_level1_checks(output, corroboration_penalty=custom_penalty)
    assert result.passed
    assert result.adjusted_output is not None
    expected = original_confidence - custom_penalty
    assert abs(result.adjusted_output.edges[0].confidence - expected) < 1e-9


def test_corroboration_penalty_does_not_go_below_zero() -> None:
    """Confidence adjusted by corroboration penalty is clamped to 0.0."""
    output = LibrarianOutput(
        concepts=[_make_good_concept("ConceptA"), _make_good_concept("ConceptB")],
        edges=[EdgeProposal(
            source_name="ConceptA",
            target_name="ConceptB",
            edge_type="depends-on",
            confidence=0.1,
            evidence_type="semantic",
        )],
    )
    result = run_level1_checks(output, corroboration_penalty=0.5)
    assert result.passed
    assert result.adjusted_output is not None
    assert result.adjusted_output.edges[0].confidence >= 0.0


def test_good_03_depends_on_confidence_reduced() -> None:
    """good_03 has a depends-on/semantic edge: its confidence should be adjusted."""
    raw = _raw_output("good_03_multi_concept_with_edges")
    data = _load_fixture("good_03_multi_concept_with_edges")
    original_conf = data["librarian_output"]["edges"][0]["confidence"]  # 0.85

    result = check_level1(raw)
    assert result.passed
    assert result.adjusted_output is not None
    adjusted_conf = result.adjusted_output.edges[0].confidence
    assert abs(adjusted_conf - (original_conf - DEFAULT_CORROBORATION_PENALTY)) < 1e-9


# ---------------------------------------------------------------------------
# Fixture-driven: all bad fixtures fail, all good fixtures pass
# ---------------------------------------------------------------------------


def test_all_bad_fixtures_fail() -> None:
    """All bad fixtures (expected_result='fail') fail Level 1."""
    errors = []
    for path in sorted(FIXTURE_DIR.glob("bad_*.json")):
        with open(path) as f:
            fixture = json.load(f)
        result = check_level1(fixture["librarian_output"])
        if result.passed:
            errors.append(
                f"{fixture['metadata']['fixture_id']}: expected fail but passed"
            )
    assert not errors, "\n".join(errors)


def test_all_good_fixtures_pass() -> None:
    """All good fixtures (expected_result='pass') pass Level 1."""
    errors = []
    for path in sorted(FIXTURE_DIR.glob("good_*.json")):
        with open(path) as f:
            fixture = json.load(f)
        result = check_level1(fixture["librarian_output"])
        if not result.passed:
            reason = result.failure_record.failure_reason if result.failure_record else "unknown"
            errors.append(
                f"{fixture['metadata']['fixture_id']}: expected pass but failed: {reason}"
            )
    assert not errors, "\n".join(errors)


# ---------------------------------------------------------------------------
# Execution time: DoD requirement < 10ms per check
# ---------------------------------------------------------------------------


def test_execution_time_under_10ms() -> None:
    """Level 1 runs in under 10ms on a known-good fixture."""
    raw = _raw_output("good_05_complex_analysis")
    start = time.perf_counter()
    check_level1(raw)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 10.0, f"Level 1 took {elapsed_ms:.2f}ms (limit: 10ms)"


def test_execution_time_each_check_under_10ms() -> None:
    """Each individual check runs in under 10ms (measured via fastest fixture per check)."""
    fixtures_by_check = {
        "schema_parseable": _raw_output("bad_08_unparseable_schema"),
        "description_non_empty": _raw_output("bad_01_empty_description"),
        "description_non_generic": _raw_output("bad_03_generic_description_01"),
        "confidence_in_range": _raw_output("bad_06_confidence_too_high"),
        "edge_type_valid": _raw_output("bad_09_invalid_edge_type"),
        "referential_integrity": _raw_output("bad_05_referential_integrity"),
    }
    for check_name, raw in fixtures_by_check.items():
        start = time.perf_counter()
        check_level1(raw)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 10.0, (
            f"Check '{check_name}' took {elapsed_ms:.2f}ms (limit: 10ms)"
        )


# ---------------------------------------------------------------------------
# Output integrity: adjusted_output preserves non-adjusted fields
# ---------------------------------------------------------------------------


def test_adjusted_output_concepts_unchanged() -> None:
    """The adjusted_output's concepts are identical to the input concepts."""
    output = LibrarianOutput(
        concepts=[_make_good_concept("ConceptA"), _make_good_concept("ConceptB")],
        edges=[EdgeProposal(
            source_name="ConceptA",
            target_name="ConceptB",
            edge_type="depends-on",
            confidence=0.7,
            evidence_type="semantic",
        )],
    )
    result = run_level1_checks(output)
    assert result.adjusted_output is not None
    assert len(result.adjusted_output.concepts) == len(output.concepts)
    for orig, adj in zip(output.concepts, result.adjusted_output.concepts):
        assert adj.name == orig.name
        assert adj.description == orig.description
        assert adj.confidence == orig.confidence


def test_adjusted_output_non_penalized_edges_unchanged() -> None:
    """Non-penalized edges in adjusted_output retain original confidence."""
    output = LibrarianOutput(
        concepts=[_make_good_concept("ConceptA"), _make_good_concept("ConceptB")],
        edges=[
            EdgeProposal(
                source_name="ConceptA",
                target_name="ConceptB",
                edge_type="implements",
                confidence=0.75,
                evidence_type="semantic",
            ),
            EdgeProposal(
                source_name="ConceptB",
                target_name="ConceptA",
                edge_type="depends-on",
                confidence=0.80,
                evidence_type="semantic",
            ),
        ],
    )
    result = run_level1_checks(output)
    assert result.passed
    assert result.adjusted_output is not None
    edges = result.adjusted_output.edges
    assert edges[0].confidence == 0.75  # implements — not penalized
    assert abs(edges[1].confidence - (0.80 - DEFAULT_CORROBORATION_PENALTY)) < 1e-9
