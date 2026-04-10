"""ReviewService — human review actions and error profiling (ERD §4.4.4).

Layer 2 (knowledge/) — may import from models/, storage/, config.py.
No imports from structural/, semantic/, retrieval/ (arch:layer-flow).

Handles the three human review actions from the Level 2 audit UI:
- verify: marks concept as verified, boosts confidence
- correct: records a correction with an error_type
- flag:   applies needs-review label and creates a review_concept WorkItem

Provides get_error_profile() to aggregate ReviewOutcomes into an error
distribution, consumed by the audit UI (Epic 11).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel

from apriori.models.concept import Concept
from apriori.models.review_outcome import ReviewOutcome
from apriori.models.work_item import WorkItem
from apriori.storage.protocol import KnowledgeStore


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

class ErrorProfile(BaseModel):
    """Aggregated summary of ReviewOutcomes over a time window.

    Attributes:
        total_outcomes: Total number of ReviewOutcomes within the window.
        action_counts: Distribution of outcomes by action type.
        error_type_counts: Distribution of corrected outcomes by error_type.
            Only outcomes with action="corrected" (which always have error_type)
            contribute to this mapping.
        window_days: The time window used for aggregation.
    """

    total_outcomes: int
    action_counts: dict[str, int]
    error_type_counts: dict[str, int]
    window_days: int


# ---------------------------------------------------------------------------
# ReviewService
# ---------------------------------------------------------------------------

class ReviewService:
    """Applies human review actions to concepts and aggregates error profiles.

    All three review actions (verify, correct, flag) atomically:
    1. Update the concept in the store.
    2. Record a ReviewOutcome in the store.
    3. (flag only) Create a review_concept WorkItem.

    The store is the single source of truth — all state is persisted through
    the KnowledgeStore protocol (arch:no-raw-sql).
    """

    _CONFIDENCE_BOOST = 0.1

    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store

    # -------------------------------------------------------------------------
    # verify_concept
    # -------------------------------------------------------------------------

    def verify_concept(
        self, concept_id: uuid.UUID, reviewer: str
    ) -> tuple[Concept, ReviewOutcome]:
        """Mark a concept as human-verified.

        Sets ``verified_by`` and ``last_verified`` on the concept. Boosts
        ``confidence`` by 0.1, capped at 1.0. Records a ReviewOutcome with
        action="verified".

        Args:
            concept_id: UUID of the concept to verify.
            reviewer: Identifier of the human reviewer.

        Returns:
            Tuple of (updated Concept, recorded ReviewOutcome).

        Raises:
            KeyError: If no concept with concept_id exists.
        """
        concept = self._require_concept(concept_id)
        now = datetime.now(timezone.utc)

        updated_confidence = min(1.0, concept.confidence + self._CONFIDENCE_BOOST)
        updated = concept.model_copy(
            update={
                "verified_by": reviewer,
                "last_verified": now,
                "confidence": updated_confidence,
                "updated_at": now,
            }
        )
        saved_concept = self._store.update_concept(updated)

        outcome = ReviewOutcome(
            concept_id=concept_id,
            reviewer=reviewer,
            action="verified",
        )
        saved_outcome = self._store.create_review_outcome(outcome)

        return saved_concept, saved_outcome

    # -------------------------------------------------------------------------
    # correct_concept
    # -------------------------------------------------------------------------

    def correct_concept(
        self,
        concept_id: uuid.UUID,
        reviewer: str,
        error_type: str,
        correction_details: Optional[str] = None,
        description: Optional[str] = None,
        relationships: Optional[list[dict[str, Any]]] = None,
    ) -> tuple[Concept, ReviewOutcome]:
        """Record a human correction for a concept.

        Updates the concept's ``updated_at`` timestamp and records a
        ReviewOutcome with action="corrected", the given error_type, and
        optional correction_details.

        Args:
            concept_id: UUID of the concept to correct.
            reviewer: Identifier of the human reviewer.
            error_type: Classification of the error. Must be one of the
                valid error types defined in ReviewOutcome.
            correction_details: Optional free-form description of the
                specific correction made.

        Returns:
            Tuple of (updated Concept, recorded ReviewOutcome).

        Raises:
            KeyError: If no concept with concept_id exists.
            ValueError: If error_type is not a valid error type.
        """
        concept = self._require_concept(concept_id)
        now = datetime.now(timezone.utc)

        updated_metadata = dict(concept.metadata or {})
        if relationships is not None:
            updated_metadata["relationship_corrections"] = relationships

        update_payload: dict[str, Any] = {"updated_at": now}
        if description is not None:
            update_payload["description"] = description
        if relationships is not None:
            update_payload["metadata"] = updated_metadata

        updated = concept.model_copy(update=update_payload)
        saved_concept = self._store.update_concept(updated)

        outcome = ReviewOutcome(
            concept_id=concept_id,
            reviewer=reviewer,
            action="corrected",
            error_type=error_type,
            correction_details=correction_details,
        )
        saved_outcome = self._store.create_review_outcome(outcome)

        return saved_concept, saved_outcome

    # -------------------------------------------------------------------------
    # flag_concept
    # -------------------------------------------------------------------------

    def flag_concept(
        self, concept_id: uuid.UUID, reviewer: str
    ) -> tuple[Concept, ReviewOutcome, WorkItem]:
        """Flag a concept for human review.

        Applies the "needs-review" label to the concept. Records a
        ReviewOutcome with action="flagged". Creates a "review_concept"
        WorkItem linked to the concept.

        Args:
            concept_id: UUID of the concept to flag.
            reviewer: Identifier of the human reviewer.

        Returns:
            Tuple of (updated Concept, recorded ReviewOutcome, created WorkItem).

        Raises:
            KeyError: If no concept with concept_id exists.
        """
        concept = self._require_concept(concept_id)
        now = datetime.now(timezone.utc)

        updated_labels = set(concept.labels) | {"needs-review"}
        updated = concept.model_copy(
            update={"labels": updated_labels, "updated_at": now}
        )
        saved_concept = self._store.update_concept(updated)

        outcome = ReviewOutcome(
            concept_id=concept_id,
            reviewer=reviewer,
            action="flagged",
        )
        saved_outcome = self._store.create_review_outcome(outcome)

        work_item = WorkItem(
            item_type="review_concept",
            concept_id=concept_id,
            description=f"Human reviewer '{reviewer}' flagged concept for review.",
        )
        saved_work_item = self._store.create_work_item(work_item)

        return saved_concept, saved_outcome, saved_work_item

    # -------------------------------------------------------------------------
    # get_error_profile
    # -------------------------------------------------------------------------

    def get_error_profile(self, days: int = 30) -> ErrorProfile:
        """Aggregate ReviewOutcomes into an error distribution.

        Fetches all ReviewOutcomes, filters to those within the last ``days``
        days, and groups by action type and error_type.

        Args:
            days: Lookback window in days. Defaults to 30.

        Returns:
            ErrorProfile with total_outcomes, action_counts, and
            error_type_counts for the specified window.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        all_outcomes = self._store.list_review_outcomes()

        windowed = [
            o for o in all_outcomes
            if _ensure_tz(o.created_at) >= cutoff
        ]

        action_counts: dict[str, int] = {}
        error_type_counts: dict[str, int] = {}

        for outcome in windowed:
            action_counts[outcome.action] = action_counts.get(outcome.action, 0) + 1
            if outcome.error_type is not None:
                error_type_counts[outcome.error_type] = (
                    error_type_counts.get(outcome.error_type, 0) + 1
                )

        return ErrorProfile(
            total_outcomes=len(windowed),
            action_counts=action_counts,
            error_type_counts=error_type_counts,
            window_days=days,
        )

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _require_concept(self, concept_id: uuid.UUID) -> Concept:
        """Return concept or raise KeyError if not found."""
        concept = self._store.get_concept(concept_id)
        if concept is None:
            raise KeyError(f"Concept {concept_id} not found")
        return concept


def _ensure_tz(dt: datetime) -> datetime:
    """Attach UTC timezone to a naive datetime, leave aware datetimes unchanged."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
