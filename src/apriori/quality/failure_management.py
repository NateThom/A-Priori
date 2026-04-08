"""Failure Management and Escalation (ERD §4.4.3).

Orchestrates the failure recording and escalation lifecycle for work items in the
librarian loop. When a work item fails either Level 1 or Level 1.5, the caller
builds a FailureRecord and passes it to ``record_failure_and_check_escalation``.

This module:
1. Appends the FailureRecord to the WorkItem via ``KnowledgeStore.record_failure``.
2. Checks whether ``failure_count`` has reached the escalation threshold.
3. If the threshold is reached and the item is not already escalated:
   - Sets ``escalated=True`` via ``KnowledgeStore.escalate_work_item``.
   - Applies the ``needs-human-review`` label to the associated Concept, if found.

Usage::

    from apriori.quality.failure_management import (
        failure_record_from_level15,
        record_failure_and_check_escalation,
    )

    # After a Level 1 failure (FailureRecord already created by level1.py):
    record_failure_and_check_escalation(store, work_item_id, level1_result.failure_record)

    # After a Level 1.5 failure:
    record = failure_record_from_level15(assessment, model_used="claude-sonnet-4-6",
                                         prompt_template="level15_co_regulation_v1")
    record_failure_and_check_escalation(store, work_item_id, record)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from apriori.models.co_regulation_assessment import CoRegulationAssessment
from apriori.models.work_item import FailureRecord, WorkItem
from apriori.storage.protocol import KnowledgeStore

#: Label applied to a Concept when its associated WorkItem is escalated.
ESCALATION_LABEL = "needs-human-review"

#: Default number of failures before a work item is escalated.
DEFAULT_ESCALATION_THRESHOLD = 3


def failure_record_from_level15(
    assessment: CoRegulationAssessment,
    model_used: str,
    prompt_template: str,
) -> FailureRecord:
    """Build a FailureRecord from a failed Level 1.5 co-regulation assessment.

    Captures the three dimension scores as ``quality_scores`` and the actionable
    reviewer feedback in ``reviewer_feedback`` so the next retry attempt can
    adjust its prompt strategy.

    Args:
        assessment: The failing CoRegulationAssessment (composite_pass=False).
        model_used: The model that performed the co-regulation review.
        prompt_template: Identifier for the prompt template used (e.g.
            ``"level15_co_regulation_v1"``).

    Returns:
        A FailureRecord with all four core fields populated plus
        ``quality_scores`` and ``reviewer_feedback``.
    """
    return FailureRecord(
        attempted_at=datetime.now(timezone.utc),
        model_used=model_used,
        prompt_template=prompt_template,
        failure_reason=(
            "Level 1.5: co-regulation check failed "
            f"(specificity={assessment.specificity:.2f}, "
            f"structural_corroboration={assessment.structural_corroboration:.2f}, "
            f"completeness={assessment.completeness:.2f})"
        ),
        quality_scores={
            "specificity": assessment.specificity,
            "structural_corroboration": assessment.structural_corroboration,
            "completeness": assessment.completeness,
        },
        reviewer_feedback=assessment.feedback,
    )


def record_failure_and_check_escalation(
    store: KnowledgeStore,
    work_item_id: uuid.UUID,
    record: FailureRecord,
    escalation_threshold: int = DEFAULT_ESCALATION_THRESHOLD,
) -> WorkItem:
    """Record a work item failure and escalate if the threshold is reached.

    This is the single entry point for all failure recording in the librarian
    loop. It handles both Level 1 and Level 1.5 failures identically — the
    difference is captured in the FailureRecord fields, not here.

    Escalation triggers when ``failure_count >= escalation_threshold`` and the
    item has not already been escalated. On escalation:
    - ``WorkItem.escalated`` is set to ``True``.
    - The ``needs-human-review`` label is added to the associated Concept.
      If the Concept is not found in the store, label application is silently
      skipped — the escalation flag is still set.

    Args:
        store: The KnowledgeStore to persist state to.
        work_item_id: UUID of the WorkItem that failed.
        record: FailureRecord capturing diagnostic context for this failure.
        escalation_threshold: Number of failures before escalation. Default: 3.

    Returns:
        The updated WorkItem after failure recording (and escalation if triggered).

    Raises:
        KeyError: If no WorkItem with ``work_item_id`` exists in the store.
    """
    updated = store.record_failure(work_item_id, record)

    if updated.failure_count >= escalation_threshold and not updated.escalated:
        updated = store.escalate_work_item(work_item_id)
        _apply_escalation_label(store, updated.concept_id)

    return updated


def _apply_escalation_label(store: KnowledgeStore, concept_id: uuid.UUID) -> None:
    """Add the needs-human-review label to a Concept if it exists in the store.

    Silently skips label application when the Concept is not found, as the
    escalation flag on the WorkItem is authoritative.

    Args:
        store: The KnowledgeStore to read and update the Concept from.
        concept_id: UUID of the Concept to label.
    """
    concept = store.get_concept(concept_id)
    if concept is None:
        return
    if ESCALATION_LABEL not in concept.labels:
        concept.labels.add(ESCALATION_LABEL)
        concept.updated_at = datetime.now(timezone.utc)
        store.update_concept(concept)
