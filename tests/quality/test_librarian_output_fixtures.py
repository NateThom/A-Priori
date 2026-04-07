"""Tests for Story 7.2: Librarian Output Test Fixtures.

AC traceability:

AC1: Given the fixture set, when reviewed, then it includes at least 5 known-good
     outputs and at least 8 known-bad outputs covering each Level 1 failure mode:
     empty description, generic/boilerplate description, referential integrity
     violation, confidence out of range, unparseable schema, invalid edge type.

AC2: Given each fixture, when it includes metadata, then the metadata documents
     which checks it should pass and which it should fail.

AC3: Given the fixtures, when used in tests, then they are loadable from a
     standard location (tests/fixtures/librarian_outputs/).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from apriori.models.librarian_output import LibrarianOutput


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "librarian_outputs"

# Canonical names for the six Level 1 failure modes (used as check names in metadata)
LEVEL1_CHECKS: frozenset[str] = frozenset(
    {
        "schema_parseable",       # LLM output can be parsed as LibrarianOutput structure
        "description_non_empty",  # No concept has an empty/whitespace-only description
        "description_non_generic",# No concept has a generic/boilerplate description
        "confidence_in_range",    # All confidences are within [0.0, 1.0]
        "edge_type_valid",        # All edge types are in the valid vocabulary
        "referential_integrity",  # All edge source/target names reference concepts in the output
    }
)

REQUIRED_METADATA_FIELDS: frozenset[str] = frozenset(
    {"fixture_id", "description", "expected_result", "checks_that_pass", "checks_that_fail"}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_all_fixtures() -> list[dict[str, Any]]:
    """Load all JSON fixtures from the standard fixture directory."""
    fixtures = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        with open(path) as f:
            fixtures.append(json.load(f))
    return fixtures


def _good_fixtures(all_fixtures: list[dict]) -> list[dict]:
    return [f for f in all_fixtures if f["metadata"]["expected_result"] == "pass"]


def _bad_fixtures(all_fixtures: list[dict]) -> list[dict]:
    return [f for f in all_fixtures if f["metadata"]["expected_result"] == "fail"]


# ---------------------------------------------------------------------------
# AC3: Loadability — fixtures are at the standard location
# ---------------------------------------------------------------------------


def test_fixture_directory_exists() -> None:
    """Given the fixtures, when used in tests, then they are loadable from
    tests/fixtures/librarian_outputs/."""
    assert FIXTURE_DIR.is_dir(), (
        f"Fixture directory not found at expected location: {FIXTURE_DIR}"
    )


def test_fixture_directory_contains_json_files() -> None:
    """Given the fixture directory, it must contain at least one JSON file."""
    json_files = list(FIXTURE_DIR.glob("*.json"))
    assert len(json_files) > 0, f"No JSON files found in {FIXTURE_DIR}"


def test_all_fixtures_loadable_as_json() -> None:
    """Given each fixture file, it must be valid JSON."""
    errors = []
    for path in FIXTURE_DIR.glob("*.json"):
        try:
            with open(path) as f:
                json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"{path.name}: {e}")
    assert not errors, "Invalid JSON files:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# AC1: Fixture counts — at least 5 good and 8 bad
# ---------------------------------------------------------------------------


def test_at_least_5_good_fixtures() -> None:
    """Given the fixture set, it includes at least 5 known-good outputs."""
    all_fixtures = _load_all_fixtures()
    good = _good_fixtures(all_fixtures)
    assert len(good) >= 5, (
        f"Expected at least 5 good fixtures, found {len(good)}: "
        + str([f["metadata"]["fixture_id"] for f in good])
    )


def test_at_least_8_bad_fixtures() -> None:
    """Given the fixture set, it includes at least 8 known-bad outputs."""
    all_fixtures = _load_all_fixtures()
    bad = _bad_fixtures(all_fixtures)
    assert len(bad) >= 8, (
        f"Expected at least 8 bad fixtures, found {len(bad)}: "
        + str([f["metadata"]["fixture_id"] for f in bad])
    )


def test_all_level1_failure_modes_covered() -> None:
    """Given the bad fixtures, each Level 1 failure mode is covered by at least
    one bad fixture (AC1: covers empty description, generic description,
    referential integrity, confidence out of range, unparseable schema,
    invalid edge type)."""
    all_fixtures = _load_all_fixtures()
    bad = _bad_fixtures(all_fixtures)

    covered_failure_modes: set[str] = set()
    for fixture in bad:
        covered_failure_modes.update(fixture["metadata"]["checks_that_fail"])

    uncovered = LEVEL1_CHECKS - covered_failure_modes
    assert not uncovered, (
        f"These Level 1 failure modes have no bad fixture covering them: {uncovered}"
    )


# ---------------------------------------------------------------------------
# AC2: Metadata — each fixture documents which checks pass and fail
# ---------------------------------------------------------------------------


def test_each_fixture_has_required_metadata_fields() -> None:
    """Given each fixture, when it includes metadata, then the metadata
    documents which checks it should pass and which it should fail."""
    all_fixtures = _load_all_fixtures()
    errors = []
    for fixture in all_fixtures:
        fixture_id = fixture.get("metadata", {}).get("fixture_id", "<unknown>")
        if "metadata" not in fixture:
            errors.append(f"{fixture_id}: missing 'metadata' key")
            continue
        meta = fixture["metadata"]
        missing = REQUIRED_METADATA_FIELDS - set(meta.keys())
        if missing:
            errors.append(f"{fixture_id}: missing metadata fields {missing}")
    assert not errors, "Metadata validation errors:\n" + "\n".join(errors)


def test_metadata_expected_result_is_pass_or_fail() -> None:
    """Each fixture's metadata.expected_result must be 'pass' or 'fail'."""
    all_fixtures = _load_all_fixtures()
    errors = []
    for fixture in all_fixtures:
        meta = fixture["metadata"]
        if meta["expected_result"] not in ("pass", "fail"):
            errors.append(
                f"{meta['fixture_id']}: expected_result must be 'pass' or 'fail', "
                f"got '{meta['expected_result']}'"
            )
    assert not errors, "\n".join(errors)


def test_metadata_checks_are_known_level1_check_names() -> None:
    """Check names in metadata must be drawn from the six Level 1 check names."""
    all_fixtures = _load_all_fixtures()
    errors = []
    for fixture in all_fixtures:
        meta = fixture["metadata"]
        all_listed = set(meta["checks_that_pass"]) | set(meta["checks_that_fail"])
        unknown = all_listed - LEVEL1_CHECKS
        if unknown:
            errors.append(f"{meta['fixture_id']}: unknown check names {unknown}")
    assert not errors, "\n".join(errors)


def test_metadata_checks_are_exhaustive() -> None:
    """Every fixture must list every Level 1 check in exactly one of
    checks_that_pass or checks_that_fail (no check may be omitted or
    listed in both)."""
    all_fixtures = _load_all_fixtures()
    errors = []
    for fixture in all_fixtures:
        meta = fixture["metadata"]
        passing = set(meta["checks_that_pass"])
        failing = set(meta["checks_that_fail"])

        overlap = passing & failing
        if overlap:
            errors.append(
                f"{meta['fixture_id']}: checks listed in both pass and fail: {overlap}"
            )

        all_listed = passing | failing
        missing = LEVEL1_CHECKS - all_listed
        if missing:
            errors.append(
                f"{meta['fixture_id']}: Level 1 checks not documented: {missing}"
            )
    assert not errors, "\n".join(errors)


def test_good_fixtures_fail_no_checks() -> None:
    """Good fixtures (expected_result='pass') must have an empty checks_that_fail list."""
    all_fixtures = _load_all_fixtures()
    errors = []
    for fixture in _good_fixtures(all_fixtures):
        meta = fixture["metadata"]
        if meta["checks_that_fail"]:
            errors.append(
                f"{meta['fixture_id']}: good fixture has failing checks: "
                f"{meta['checks_that_fail']}"
            )
    assert not errors, "\n".join(errors)


def test_bad_fixtures_fail_at_least_one_check() -> None:
    """Bad fixtures (expected_result='fail') must fail at least one Level 1 check."""
    all_fixtures = _load_all_fixtures()
    errors = []
    for fixture in _bad_fixtures(all_fixtures):
        meta = fixture["metadata"]
        if not meta["checks_that_fail"]:
            errors.append(
                f"{meta['fixture_id']}: bad fixture has no failing checks listed"
            )
    assert not errors, "\n".join(errors)


# ---------------------------------------------------------------------------
# Structural: good fixtures parse; unparseable fixtures do not
# ---------------------------------------------------------------------------


def test_good_fixtures_parse_as_librarian_output() -> None:
    """Given good fixtures (expected_result='pass'), when validated against
    LibrarianOutput, then Pydantic validation succeeds."""
    all_fixtures = _load_all_fixtures()
    errors = []
    for fixture in _good_fixtures(all_fixtures):
        meta = fixture["metadata"]
        try:
            result = LibrarianOutput.model_validate(fixture["librarian_output"])
            assert isinstance(result, LibrarianOutput)
        except (ValidationError, Exception) as e:
            errors.append(f"{meta['fixture_id']}: failed to parse: {e}")
    assert not errors, "\n".join(errors)


def test_unparseable_schema_fixtures_fail_to_parse() -> None:
    """Given bad fixtures where 'schema_parseable' is in checks_that_fail,
    when validated against LibrarianOutput, then Pydantic validation fails."""
    all_fixtures = _load_all_fixtures()
    errors = []
    for fixture in _bad_fixtures(all_fixtures):
        meta = fixture["metadata"]
        if "schema_parseable" not in meta["checks_that_fail"]:
            continue
        try:
            LibrarianOutput.model_validate(fixture["librarian_output"])
            errors.append(
                f"{meta['fixture_id']}: expected parse failure for unparseable schema "
                f"but LibrarianOutput.model_validate() succeeded"
            )
        except (ValidationError, TypeError, KeyError, Exception):
            pass  # Expected: this fixture should fail to parse
    assert not errors, "\n".join(errors)


def test_good_fixtures_have_non_empty_concepts() -> None:
    """Good fixtures must contain at least one concept."""
    all_fixtures = _load_all_fixtures()
    errors = []
    for fixture in _good_fixtures(all_fixtures):
        meta = fixture["metadata"]
        output = LibrarianOutput.model_validate(fixture["librarian_output"])
        if not output.concepts:
            errors.append(f"{meta['fixture_id']}: good fixture has no concepts")
    assert not errors, "\n".join(errors)
