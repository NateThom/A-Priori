"""Blast radius accuracy validation harness — Story 12.7 (AP-105).

Validates blast radius predictions against historical PRs by comparing
A-Priori's predicted impact set to the actual set of files changed in each
PR, per PRD §9.1 and the S-4 validation methodology.

Methodology:
1. For a PR with changed files F, identify "seed files" — files whose
   associated concepts have pre-computed impact profiles.
2. actual_other = F - seed_files (the non-seed changed files that are
   the prediction targets).
3. Run query_blast_radius for each concept belonging to a seed file.
   Collect all predicted file paths (from concept code_references).
4. Compute per-PR recall = |predicted ∩ actual_other| / |actual_other|.
5. Compute per-PR precision = |predicted ∩ actual_other| / |predicted|.
6. Aggregate with macro-averaging across all PRs.

Targets (PRD §9.1): recall ≥ 70%, precision ≥ 50%.

Layer: validation/ — reads from KnowledgeStore, never writes.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from apriori.retrieval.blast_radius_query import query_blast_radius
from apriori.storage.protocol import KnowledgeStore

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RECALL_TARGET: float = 0.70
PRECISION_TARGET: float = 0.50


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class PRRecord(BaseModel):
    """A single historical PR described by its changed files."""

    pr_id: str
    changed_files: list[str]


class PRValidationResult(BaseModel):
    """Per-PR validation metrics."""

    pr_id: str
    seed_files: frozenset[str]
    """Changed files whose concepts have impact profiles (blast radius origins)."""
    actual_files: frozenset[str]
    """All files changed in this PR (ground truth)."""
    predicted_files: frozenset[str]
    """Files predicted by blast radius across all seed concepts."""
    true_positives: frozenset[str]
    """predicted_files ∩ actual_other (correctly predicted changes)."""
    false_positives: frozenset[str]
    """predicted_files - actual_other (over-predicted)."""
    false_negatives: frozenset[str]
    """actual_other - predicted_files (missed changes)."""
    recall: float
    """Fraction of actual_other files that were correctly predicted."""
    precision: float
    """Fraction of predicted files that were actually in actual_other."""


class ValidationReport(BaseModel):
    """Aggregate validation report across all PRs."""

    pr_results: list[PRValidationResult]
    aggregate_recall: float
    aggregate_precision: float
    passes_recall_target: bool = Field(description="aggregate_recall >= 0.70")
    passes_precision_target: bool = Field(description="aggregate_precision >= 0.50")
    failure_patterns: list[str]
    """Human-readable descriptions of common failure patterns."""


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class BlastRadiusValidator:
    """Validates blast radius accuracy against historical PR records.

    Args:
        store: KnowledgeStore containing concepts and pre-computed impact profiles.
    """

    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def validate_pr(self, pr: PRRecord) -> PRValidationResult:
        """Compute blast radius accuracy metrics for a single PR.

        Args:
            pr: A PR record with changed file paths.

        Returns:
            Per-PR validation result with recall, precision, TP, FP, FN.
        """
        changed_files = frozenset(pr.changed_files)

        # Step 1: Identify seed files — files with at least one concept
        # that has a non-None impact profile.
        seed_files: set[str] = set()
        for file_path in pr.changed_files:
            concepts = self._store.search_by_file(file_path)
            if any(c.impact_profile is not None for c in concepts):
                seed_files.add(file_path)

        # Step 2: actual_other = changed files that are not seed files.
        # These are the "prediction targets" — files we expect the blast
        # radius to have flagged as impacted.
        actual_other: frozenset[str] = changed_files - frozenset(seed_files)

        # Step 3: Collect predicted files by running blast_radius for all
        # concepts in each seed file.
        predicted_files: set[str] = set()
        for seed_file in seed_files:
            concepts = self._store.search_by_file(seed_file)
            for concept in concepts:
                entries = query_blast_radius(self._store, str(concept.id))
                for entry in entries:
                    target = self._store.get_concept(entry.concept_id)
                    if target is not None:
                        for ref in target.code_references:
                            predicted_files.add(ref.file_path)

        predicted = frozenset(predicted_files)

        # Step 4: Compute TP, FP, FN.
        true_positives = predicted & actual_other
        false_positives = predicted - actual_other
        false_negatives = actual_other - predicted

        # Step 5: Recall and precision (0.0 when denominators are zero).
        recall = (
            len(true_positives) / len(actual_other) if actual_other else 0.0
        )
        precision = (
            len(true_positives) / len(predicted) if predicted else 0.0
        )

        return PRValidationResult(
            pr_id=pr.pr_id,
            seed_files=frozenset(seed_files),
            actual_files=changed_files,
            predicted_files=predicted,
            true_positives=true_positives,
            false_positives=false_positives,
            false_negatives=false_negatives,
            recall=recall,
            precision=precision,
        )

    def validate(self, prs: list[PRRecord]) -> ValidationReport:
        """Run validation across a list of PRs and return an aggregate report.

        Args:
            prs: List of PR records. Must contain at least one entry.

        Returns:
            ValidationReport with per-PR results, aggregate metrics, and
            identified failure patterns.

        Raises:
            ValueError: If *prs* is empty.
        """
        if not prs:
            raise ValueError("validate() requires at least one PR record")

        pr_results = [self.validate_pr(pr) for pr in prs]

        # Macro-average recall and precision across all PRs.
        aggregate_recall = sum(r.recall for r in pr_results) / len(pr_results)
        aggregate_precision = sum(r.precision for r in pr_results) / len(pr_results)

        failure_patterns = self._identify_failure_patterns(pr_results)

        return ValidationReport(
            pr_results=pr_results,
            aggregate_recall=aggregate_recall,
            aggregate_precision=aggregate_precision,
            passes_recall_target=aggregate_recall >= RECALL_TARGET,
            passes_precision_target=aggregate_precision >= PRECISION_TARGET,
            failure_patterns=failure_patterns,
        )

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _identify_failure_patterns(results: list[PRValidationResult]) -> list[str]:
        """Identify common failure patterns from per-PR results.

        Looks for:
        - Files that are frequently missed (common false negatives).
        - Files that are frequently over-predicted (common false positives).

        Returns a list of human-readable pattern descriptions.
        """
        patterns: list[str] = []
        if not results:
            return patterns

        fn_counts: Counter[str] = Counter()
        fp_counts: Counter[str] = Counter()
        for result in results:
            fn_counts.update(result.false_negatives)
            fp_counts.update(result.false_positives)

        # Threshold: at least 10% of PRs or 2, whichever is greater.
        threshold = max(2, int(len(results) * 0.10))

        for file_path, count in fn_counts.most_common():
            if count < threshold:
                break
            patterns.append(
                f"Frequently missed (false negative in {count}/{len(results)} PRs): {file_path}"
            )

        for file_path, count in fp_counts.most_common():
            if count < threshold:
                break
            patterns.append(
                f"Frequently over-predicted (false positive in {count}/{len(results)} PRs): {file_path}"
            )

        return patterns
