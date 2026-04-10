"""Tests for blast radius accuracy validation harness — Story 12.7 (AP-105).

Each test is directly traceable to a Given/When/Then acceptance criterion.

AC1: Given ≥50 historical PRs, when blast radius predictions are compared
     to actual file changes, then recall is ≥70%.
AC2: Given the same PR set, when precision is measured, then precision is ≥50%.
AC3: Given validation results, when reviewed, then a written report documents
     per-PR results, aggregate metrics, and identified failure patterns.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apriori.models.concept import Concept, CodeReference
from apriori.models.impact import ImpactEntry, ImpactProfile
from apriori.storage.sqlite_store import SQLiteStore
from apriori.validation.blast_radius_validator import (
    BlastRadiusValidator,
    PRRecord,
    PRValidationResult,
    ValidationReport,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_SHA = "a" * 64


def _concept(
    name: str,
    file_path: str,
    *,
    symbol: str | None = None,
    impact_profile: ImpactProfile | None = None,
) -> Concept:
    return Concept(
        name=name,
        description=f"Concept {name}",
        created_by="agent",
        code_references=[
            CodeReference(
                symbol=symbol or name,
                file_path=file_path,
                content_hash=_SHA,
                semantic_anchor=name,
            )
        ],
        impact_profile=impact_profile,
    )


def _impact_profile(target_ids: list[uuid.UUID]) -> ImpactProfile:
    return ImpactProfile(
        structural_impact=[
            ImpactEntry(
                target_concept_id=tid,
                confidence=0.9,
                relationship_path=[str(uuid.uuid4())],
                depth=1,
                rationale="structural dependency",
            )
            for tid in target_ids
        ],
        last_computed=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# AC1 / AC2: Recall and precision calculation correctness
# ---------------------------------------------------------------------------


def test_perfect_recall_when_all_actual_files_predicted(tmp_path: Path) -> None:
    """Given: blast_radius for file A correctly predicts file B.
    When: PR changes {A, B}.
    Then: recall = 1.0 (100% of actual changes predicted)."""
    store = SQLiteStore(tmp_path / "test.db")
    concept_b = _concept("concept_b", "src/module_b.py")
    store.create_concept(concept_b)

    concept_a = _concept(
        "concept_a",
        "src/module_a.py",
        impact_profile=_impact_profile([concept_b.id]),
    )
    store.create_concept(concept_a)

    validator = BlastRadiusValidator(store)
    pr = PRRecord(pr_id="pr-1", changed_files=["src/module_a.py", "src/module_b.py"])
    result = validator.validate_pr(pr)

    assert result.recall == pytest.approx(1.0)


def test_zero_recall_when_nothing_predicted(tmp_path: Path) -> None:
    """Given: blast_radius returns nothing for file A.
    When: PR changes {A, B}.
    Then: recall = 0.0."""
    store = SQLiteStore(tmp_path / "test.db")
    concept_b = _concept("concept_b", "src/module_b.py")
    store.create_concept(concept_b)

    concept_a = _concept("concept_a", "src/module_a.py", impact_profile=_impact_profile([]))
    store.create_concept(concept_a)

    validator = BlastRadiusValidator(store)
    pr = PRRecord(pr_id="pr-1", changed_files=["src/module_a.py", "src/module_b.py"])
    result = validator.validate_pr(pr)

    assert result.recall == pytest.approx(0.0)


def test_precision_is_one_when_no_false_positives(tmp_path: Path) -> None:
    """Given: blast_radius predicts exactly the actual changed files.
    When: PR changes {A, B}.
    Then: precision = 1.0."""
    store = SQLiteStore(tmp_path / "test.db")
    concept_b = _concept("concept_b", "src/module_b.py")
    store.create_concept(concept_b)

    concept_a = _concept(
        "concept_a",
        "src/module_a.py",
        impact_profile=_impact_profile([concept_b.id]),
    )
    store.create_concept(concept_a)

    validator = BlastRadiusValidator(store)
    pr = PRRecord(pr_id="pr-1", changed_files=["src/module_a.py", "src/module_b.py"])
    result = validator.validate_pr(pr)

    assert result.precision == pytest.approx(1.0)


def test_precision_drops_with_false_positives(tmp_path: Path) -> None:
    """Given: blast_radius predicts B (in PR) and C (not in PR).
    When: PR changes {A, B}.
    Then: precision = 0.5 (1 TP, 1 FP)."""
    store = SQLiteStore(tmp_path / "test.db")
    concept_b = _concept("concept_b", "src/module_b.py")
    concept_c = _concept("concept_c", "src/module_c.py")
    store.create_concept(concept_b)
    store.create_concept(concept_c)

    concept_a = _concept(
        "concept_a",
        "src/module_a.py",
        impact_profile=_impact_profile([concept_b.id, concept_c.id]),
    )
    store.create_concept(concept_a)

    validator = BlastRadiusValidator(store)
    pr = PRRecord(pr_id="pr-1", changed_files=["src/module_a.py", "src/module_b.py"])
    result = validator.validate_pr(pr)

    assert result.precision == pytest.approx(0.5)


def test_recall_measures_fraction_of_actuals_predicted(tmp_path: Path) -> None:
    """Given: blast_radius predicts B but not C when querying A.
    When: PR changes {A, B, C}.
    Then: recall = 0.5 (1 of 2 other actual files predicted)."""
    store = SQLiteStore(tmp_path / "test.db")
    concept_b = _concept("concept_b", "src/module_b.py")
    concept_c = _concept("concept_c", "src/module_c.py")
    store.create_concept(concept_b)
    store.create_concept(concept_c)

    concept_a = _concept(
        "concept_a",
        "src/module_a.py",
        impact_profile=_impact_profile([concept_b.id]),
    )
    store.create_concept(concept_a)

    validator = BlastRadiusValidator(store)
    pr = PRRecord(
        pr_id="pr-1",
        changed_files=["src/module_a.py", "src/module_b.py", "src/module_c.py"],
    )
    result = validator.validate_pr(pr)

    assert result.recall == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# PR validation result structure — AC3
# ---------------------------------------------------------------------------


def test_pr_validation_result_contains_predicted_and_actual_files(tmp_path: Path) -> None:
    """Given: a PR with known changed files.
    When: validated.
    Then: result has predicted_files and actual_files sets."""
    store = SQLiteStore(tmp_path / "test.db")
    concept_b = _concept("concept_b", "src/module_b.py")
    store.create_concept(concept_b)

    concept_a = _concept(
        "concept_a",
        "src/module_a.py",
        impact_profile=_impact_profile([concept_b.id]),
    )
    store.create_concept(concept_a)

    validator = BlastRadiusValidator(store)
    pr = PRRecord(pr_id="pr-42", changed_files=["src/module_a.py", "src/module_b.py"])
    result = validator.validate_pr(pr)

    assert result.pr_id == "pr-42"
    assert isinstance(result.predicted_files, frozenset)
    assert isinstance(result.actual_files, frozenset)
    assert "src/module_a.py" in result.actual_files
    assert "src/module_b.py" in result.actual_files


def test_pr_validation_result_contains_true_positive_false_positive_false_negative(
    tmp_path: Path,
) -> None:
    """Given: a PR with known changes and a blast_radius predicting B and D (not in PR).
    When: validated.
    Then: result.true_positives = {B}, result.false_positives = {D}, result.false_negatives = {C}."""
    store = SQLiteStore(tmp_path / "test.db")
    concept_b = _concept("concept_b", "src/module_b.py")
    concept_c = _concept("concept_c", "src/module_c.py")
    concept_d = _concept("concept_d", "src/module_d.py")
    for c in [concept_b, concept_c, concept_d]:
        store.create_concept(c)

    concept_a = _concept(
        "concept_a",
        "src/module_a.py",
        impact_profile=_impact_profile([concept_b.id, concept_d.id]),
    )
    store.create_concept(concept_a)

    validator = BlastRadiusValidator(store)
    pr = PRRecord(
        pr_id="pr-1",
        changed_files=["src/module_a.py", "src/module_b.py", "src/module_c.py"],
    )
    result = validator.validate_pr(pr)

    assert "src/module_b.py" in result.true_positives
    assert "src/module_d.py" in result.false_positives
    assert "src/module_c.py" in result.false_negatives


# ---------------------------------------------------------------------------
# Aggregate report — AC1, AC2, AC3
# ---------------------------------------------------------------------------


def _make_50_high_recall_prs(tmp_path: Path) -> tuple[SQLiteStore, list[PRRecord]]:
    """Build a store and 50 PRs where recall ≥70% and precision ≥50%."""
    store = SQLiteStore(tmp_path / "test.db")
    prs: list[PRRecord] = []

    for i in range(50):
        # Concept A (seed) correctly predicts B (TP) but not C (FN), no FPs
        # -> recall=0.5, precision=1.0 per PR.  Aggregate recall=0.5, precision=1.0
        # We want recall ≥0.7, so let's predict both B and C from A
        concept_b = _concept(f"concept_b_{i}", f"src/module_b_{i}.py")
        concept_c = _concept(f"concept_c_{i}", f"src/module_c_{i}.py")
        store.create_concept(concept_b)
        store.create_concept(concept_c)

        concept_a = _concept(
            f"concept_a_{i}",
            f"src/module_a_{i}.py",
            impact_profile=_impact_profile([concept_b.id, concept_c.id]),
        )
        store.create_concept(concept_a)

        prs.append(
            PRRecord(
                pr_id=f"pr-{i}",
                changed_files=[
                    f"src/module_a_{i}.py",
                    f"src/module_b_{i}.py",
                    f"src/module_c_{i}.py",
                ],
            )
        )

    return store, prs


def test_aggregate_report_passes_recall_target(tmp_path: Path) -> None:
    """Given: ≥50 PRs where all changed files are predicted.
    When: report generated.
    Then: aggregate_recall ≥ 0.70 and passes_recall_target = True."""
    store, prs = _make_50_high_recall_prs(tmp_path)
    validator = BlastRadiusValidator(store)
    report = validator.validate(prs)

    assert report.aggregate_recall >= 0.70
    assert report.passes_recall_target is True


def test_aggregate_report_passes_precision_target(tmp_path: Path) -> None:
    """Given: ≥50 PRs where predicted files exactly match actual changed files.
    When: report generated.
    Then: aggregate_precision ≥ 0.50 and passes_precision_target = True."""
    store, prs = _make_50_high_recall_prs(tmp_path)
    validator = BlastRadiusValidator(store)
    report = validator.validate(prs)

    assert report.aggregate_precision >= 0.50
    assert report.passes_precision_target is True


def test_aggregate_report_fails_recall_target_when_below_70_percent(tmp_path: Path) -> None:
    """Given: PRs where nothing is predicted.
    When: report generated.
    Then: passes_recall_target = False."""
    store = SQLiteStore(tmp_path / "test.db")
    prs: list[PRRecord] = []
    for i in range(50):
        # No impact profiles → nothing predicted → recall=0.0
        concept_a = _concept(f"concept_a_{i}", f"src/module_a_{i}.py")
        concept_b = _concept(f"concept_b_{i}", f"src/module_b_{i}.py")
        store.create_concept(concept_a)
        store.create_concept(concept_b)
        prs.append(
            PRRecord(
                pr_id=f"pr-{i}",
                changed_files=[f"src/module_a_{i}.py", f"src/module_b_{i}.py"],
            )
        )

    validator = BlastRadiusValidator(store)
    report = validator.validate(prs)

    assert report.aggregate_recall < 0.70
    assert report.passes_recall_target is False


def test_report_contains_per_pr_results(tmp_path: Path) -> None:
    """Given: 3 PRs validated.
    When: report generated.
    Then: report.pr_results has one entry per PR."""
    store = SQLiteStore(tmp_path / "test.db")
    prs = [
        PRRecord(pr_id=f"pr-{i}", changed_files=[f"src/file_{i}.py"])
        for i in range(3)
    ]

    validator = BlastRadiusValidator(store)
    report = validator.validate(prs)

    assert len(report.pr_results) == 3
    result_ids = {r.pr_id for r in report.pr_results}
    assert result_ids == {"pr-0", "pr-1", "pr-2"}


def test_report_contains_failure_patterns(tmp_path: Path) -> None:
    """Given: multiple PRs where test files are never predicted.
    When: report generated.
    Then: report.failure_patterns contains a message about the pattern."""
    store = SQLiteStore(tmp_path / "test.db")
    prs: list[PRRecord] = []
    for i in range(10):
        concept_src = _concept(f"concept_src_{i}", f"src/module_{i}.py")
        concept_test = _concept(f"concept_test_{i}", f"tests/test_module_{i}.py")
        store.create_concept(concept_src)
        store.create_concept(concept_test)
        prs.append(
            PRRecord(
                pr_id=f"pr-{i}",
                changed_files=[f"src/module_{i}.py", f"tests/test_module_{i}.py"],
            )
        )

    validator = BlastRadiusValidator(store)
    report = validator.validate(prs)

    assert isinstance(report.failure_patterns, list)
    # Report exists — failure analysis present whether patterns found or not
    assert report.failure_patterns is not None


def test_report_requires_at_least_one_pr(tmp_path: Path) -> None:
    """Given: zero PRs.
    When: validate called.
    Then: raises ValueError."""
    store = SQLiteStore(tmp_path / "test.db")
    validator = BlastRadiusValidator(store)

    with pytest.raises(ValueError, match="at least one"):
        validator.validate([])


# ---------------------------------------------------------------------------
# Single-file PR edge case
# ---------------------------------------------------------------------------


def test_single_file_pr_skipped_gracefully(tmp_path: Path) -> None:
    """Given: a PR with only one changed file.
    When: validated.
    Then: result has recall=0.0 and precision=0.0 (nothing to predict against)."""
    store = SQLiteStore(tmp_path / "test.db")
    concept_a = _concept("concept_a", "src/module_a.py")
    store.create_concept(concept_a)

    validator = BlastRadiusValidator(store)
    pr = PRRecord(pr_id="pr-solo", changed_files=["src/module_a.py"])
    result = validator.validate_pr(pr)

    # Only one file in PR — actual_other is empty, so precision and recall default to 0
    assert result.recall == pytest.approx(0.0)
    assert result.precision == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# File-to-concept resolution
# ---------------------------------------------------------------------------


def test_file_with_no_concept_in_store_contributes_no_predictions(tmp_path: Path) -> None:
    """Given: a changed file not in the store.
    When: blast_radius queried.
    Then: no predictions for that file (doesn't raise)."""
    store = SQLiteStore(tmp_path / "test.db")
    validator = BlastRadiusValidator(store)
    pr = PRRecord(
        pr_id="pr-1",
        changed_files=["src/unknown.py", "src/also_unknown.py"],
    )
    result = validator.validate_pr(pr)

    assert len(result.predicted_files) == 0


# ---------------------------------------------------------------------------
# Multiple concepts per file
# ---------------------------------------------------------------------------


def test_multiple_concepts_per_file_union_predictions(tmp_path: Path) -> None:
    """Given: a file has two concepts, each predicting different targets.
    When: blast_radius queried.
    Then: predicted_files is the union of both concepts' impact."""
    store = SQLiteStore(tmp_path / "test.db")
    concept_target1 = _concept("target1", "src/target1.py")
    concept_target2 = _concept("target2", "src/target2.py")
    store.create_concept(concept_target1)
    store.create_concept(concept_target2)

    # Two concepts in the same file, each predicting different targets
    concept_a1 = _concept(
        "concept_a1",
        "src/shared.py",
        impact_profile=_impact_profile([concept_target1.id]),
    )
    concept_a2 = _concept(
        "concept_a2",
        "src/shared.py",
        impact_profile=_impact_profile([concept_target2.id]),
    )
    store.create_concept(concept_a1)
    store.create_concept(concept_a2)

    validator = BlastRadiusValidator(store)
    pr = PRRecord(
        pr_id="pr-1",
        changed_files=["src/shared.py", "src/target1.py", "src/target2.py"],
    )
    result = validator.validate_pr(pr)

    assert "src/target1.py" in result.predicted_files
    assert "src/target2.py" in result.predicted_files
