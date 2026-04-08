"""Tests for Story 7.5: Failure Management and Escalation (quality/failure_management.py).

AC traceability:

AC-1: Given a Level 1 failure, when the failure is recorded, then a FailureRecord is
      appended with failure_reason, model_used, prompt_template, and attempted_at.

AC-2: Given a Level 1.5 failure, when the failure is recorded, then the FailureRecord
      additionally includes quality_scores and reviewer_feedback.

AC-3: Given a work item with failure_count=2 (threshold=3), when a third failure occurs,
      then failure_count becomes 3, escalated is set to True, and the needs-human-review
      label is applied to the associated concept.

AC-4: Given an escalated item, when inspected, then all previous failure records are
      preserved with full diagnostic context.

AC-5: Given a work item with no associated concept, when escalation occurs, then
      escalation still proceeds (label application is skipped but the flag is set).
      Tested with a mock store since the SQLiteStore FK constraint prevents orphaned
      work items in production (by design).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from apriori.models.co_regulation_assessment import CoRegulationAssessment
from apriori.models.concept import Concept
from apriori.models.work_item import FailureRecord, WorkItem
from apriori.quality.failure_management import (
    failure_record_from_level15,
    record_failure_and_check_escalation,
)
from apriori.storage.sqlite_store import SQLiteStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_fm.db"


@pytest.fixture
def store(db_path: Path) -> SQLiteStore:
    return SQLiteStore(db_path)


def _make_concept(**kwargs) -> Concept:
    defaults = dict(name="TestConcept", description="A well-described concept for testing.", created_by="agent")
    defaults.update(kwargs)
    return Concept(**defaults)


def _make_work_item(concept_id: uuid.UUID, **kwargs) -> WorkItem:
    defaults = dict(
        concept_id=concept_id,
        item_type="verify_concept",
        description="Verify this concept.",
    )
    defaults.update(kwargs)
    return WorkItem(**defaults)


def _make_level1_failure_record(**kwargs) -> FailureRecord:
    """Simulates the FailureRecord produced by level1.py's _failure() function."""
    defaults = dict(
        attempted_at=datetime.now(timezone.utc),
        model_used="none",
        prompt_template="level1_consistency_checks",
        failure_reason="Level 1: empty description",
    )
    defaults.update(kwargs)
    return FailureRecord(**defaults)


def _make_failing_assessment(**kwargs) -> CoRegulationAssessment:
    """A CoRegulationAssessment that does NOT pass (composite_pass=False)."""
    defaults = dict(
        specificity=0.3,  # below 0.5 threshold
        structural_corroboration=0.2,  # below 0.3 threshold
        completeness=0.4,
        feedback="The description omits the UPSERT pattern and error handling semantics.",
    )
    defaults.update(kwargs)
    return CoRegulationAssessment(**defaults)


# ---------------------------------------------------------------------------
# AC-1: Level 1 failure records have required fields
# ---------------------------------------------------------------------------


class TestLevel1FailureRecord:
    """AC-1: Level 1 failure records include failure_reason, model_used,
    prompt_template, and attempted_at. No quality_scores or reviewer_feedback."""

    def test_level1_failure_record_has_core_fields(self, store: SQLiteStore):
        """Given a Level 1 failure record, when recorded, all core fields are present."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        record = _make_level1_failure_record(failure_reason="Level 1: confidence out of range (1.5)")
        record_failure_and_check_escalation(store, wi.id, record)

        retrieved = store.get_work_item(wi.id)
        fr = retrieved.failure_records[0]
        assert fr.failure_reason == "Level 1: confidence out of range (1.5)"
        assert fr.model_used == "none"
        assert fr.prompt_template == "level1_consistency_checks"
        assert fr.attempted_at is not None

    def test_level1_failure_record_has_no_quality_scores(self, store: SQLiteStore):
        """Level 1 failure records do not include quality_scores."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        record = _make_level1_failure_record()
        record_failure_and_check_escalation(store, wi.id, record)

        retrieved = store.get_work_item(wi.id)
        fr = retrieved.failure_records[0]
        assert fr.quality_scores is None
        assert fr.reviewer_feedback is None


# ---------------------------------------------------------------------------
# AC-2: Level 1.5 failure records include quality_scores and reviewer_feedback
# ---------------------------------------------------------------------------


class TestLevel15FailureRecord:
    """AC-2: failure_record_from_level15 builds a FailureRecord with quality_scores
    and reviewer_feedback from a CoRegulationAssessment."""

    def test_failure_record_from_level15_contains_all_required_fields(self):
        """Given a failing CoRegulationAssessment, failure_record_from_level15 returns
        a FailureRecord with failure_reason, model_used, prompt_template, attempted_at."""
        assessment = _make_failing_assessment()
        record = failure_record_from_level15(
            assessment=assessment,
            model_used="claude-sonnet-4-6",
            prompt_template="level15_co_regulation_v1",
        )

        assert record.failure_reason is not None
        assert "Level 1.5" in record.failure_reason
        assert record.model_used == "claude-sonnet-4-6"
        assert record.prompt_template == "level15_co_regulation_v1"
        assert record.attempted_at is not None

    def test_failure_record_from_level15_includes_quality_scores(self):
        """Level 1.5 FailureRecord includes quality_scores with all three dimensions."""
        assessment = _make_failing_assessment(
            specificity=0.3,
            structural_corroboration=0.2,
            completeness=0.35,
        )
        record = failure_record_from_level15(
            assessment=assessment,
            model_used="claude-sonnet-4-6",
            prompt_template="level15_co_regulation_v1",
        )

        assert record.quality_scores is not None
        assert record.quality_scores["specificity"] == pytest.approx(0.3)
        assert record.quality_scores["structural_corroboration"] == pytest.approx(0.2)
        assert record.quality_scores["completeness"] == pytest.approx(0.35)

    def test_failure_record_from_level15_includes_reviewer_feedback(self):
        """Level 1.5 FailureRecord includes reviewer_feedback from assessment."""
        feedback = "The description omits the UPSERT pattern and error handling semantics."
        assessment = _make_failing_assessment(feedback=feedback)
        record = failure_record_from_level15(
            assessment=assessment,
            model_used="claude-sonnet-4-6",
            prompt_template="level15_co_regulation_v1",
        )

        assert record.reviewer_feedback == feedback

    def test_level15_failure_record_can_be_stored_and_retrieved(self, store: SQLiteStore):
        """Level 1.5 FailureRecord with quality_scores survives a storage roundtrip."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        assessment = _make_failing_assessment(
            specificity=0.3,
            structural_corroboration=0.1,
            completeness=0.25,
            feedback="Missing error handling description.",
        )
        record = failure_record_from_level15(
            assessment=assessment,
            model_used="claude-opus-4-6",
            prompt_template="level15_co_regulation_v1",
        )
        record_failure_and_check_escalation(store, wi.id, record)

        retrieved = store.get_work_item(wi.id)
        fr = retrieved.failure_records[0]
        assert fr.quality_scores["specificity"] == pytest.approx(0.3)
        assert fr.quality_scores["structural_corroboration"] == pytest.approx(0.1)
        assert fr.quality_scores["completeness"] == pytest.approx(0.25)
        assert fr.reviewer_feedback == "Missing error handling description."


# ---------------------------------------------------------------------------
# AC-3: Escalation at threshold — failure_count=3, escalated=True, label applied
# ---------------------------------------------------------------------------


class TestEscalationAtThreshold:
    """AC-3: When failure_count reaches the threshold, escalated=True and
    needs-human-review label is applied to the concept."""

    def test_third_failure_triggers_escalation(self, store: SQLiteStore):
        """Given failure_count=2, when third failure is recorded, escalated becomes True."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id, failure_count=2)
        store.create_work_item(wi)

        record = _make_level1_failure_record()
        updated = record_failure_and_check_escalation(store, wi.id, record, escalation_threshold=3)

        assert updated.failure_count == 3
        assert updated.escalated is True

    def test_third_failure_applies_needs_human_review_label(self, store: SQLiteStore):
        """When escalation triggers, needs-human-review label is added to the concept."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id, failure_count=2)
        store.create_work_item(wi)

        record = _make_level1_failure_record()
        record_failure_and_check_escalation(store, wi.id, record, escalation_threshold=3)

        updated_concept = store.get_concept(concept.id)
        assert "needs-human-review" in updated_concept.labels

    def test_below_threshold_does_not_escalate(self, store: SQLiteStore):
        """Given failure_count=1 (threshold=3), second failure does not escalate."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id, failure_count=1)
        store.create_work_item(wi)

        record = _make_level1_failure_record()
        updated = record_failure_and_check_escalation(store, wi.id, record, escalation_threshold=3)

        assert updated.failure_count == 2
        assert updated.escalated is False

    def test_already_escalated_item_records_additional_failure(self, store: SQLiteStore):
        """An already-escalated item can still accumulate failure records."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id, failure_count=3, escalated=True)
        store.create_work_item(wi)

        record = _make_level1_failure_record()
        updated = record_failure_and_check_escalation(store, wi.id, record, escalation_threshold=3)

        assert updated.failure_count == 4
        assert updated.escalated is True
        assert len(updated.failure_records) == 1

    def test_custom_escalation_threshold(self, store: SQLiteStore):
        """Custom threshold is respected — escalation at threshold=5."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id, failure_count=4)
        store.create_work_item(wi)

        record = _make_level1_failure_record()
        updated = record_failure_and_check_escalation(store, wi.id, record, escalation_threshold=5)

        assert updated.failure_count == 5
        assert updated.escalated is True

    def test_escalation_persists_to_store(self, store: SQLiteStore):
        """After escalation, get_work_item returns escalated=True."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id, failure_count=2)
        store.create_work_item(wi)

        record = _make_level1_failure_record()
        record_failure_and_check_escalation(store, wi.id, record, escalation_threshold=3)

        retrieved = store.get_work_item(wi.id)
        assert retrieved.escalated is True


# ---------------------------------------------------------------------------
# AC-4: Escalated items preserve all failure records
# ---------------------------------------------------------------------------


class TestFailureRecordPreservation:
    """AC-4: All previous failure records are preserved with full diagnostic context."""

    def test_all_failure_records_preserved_after_escalation(self, store: SQLiteStore):
        """Given 3 failures (one per call), all 3 FailureRecords are preserved."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        records = [
            _make_level1_failure_record(failure_reason=f"Failure {i}", model_used="none")
            for i in range(3)
        ]
        for record in records:
            record_failure_and_check_escalation(store, wi.id, record, escalation_threshold=3)

        retrieved = store.get_work_item(wi.id)
        assert len(retrieved.failure_records) == 3
        reasons = {fr.failure_reason for fr in retrieved.failure_records}
        assert "Failure 0" in reasons
        assert "Failure 1" in reasons
        assert "Failure 2" in reasons

    def test_mixed_level1_and_level15_records_preserved(self, store: SQLiteStore):
        """Level 1 and Level 1.5 failure records coexist in the failure_records list."""
        concept = _make_concept()
        store.create_concept(concept)
        wi = _make_work_item(concept.id)
        store.create_work_item(wi)

        level1_record = _make_level1_failure_record(failure_reason="Level 1: empty description")
        assessment = _make_failing_assessment(feedback="Missing error handling.")
        level15_record = failure_record_from_level15(
            assessment=assessment,
            model_used="claude-sonnet-4-6",
            prompt_template="level15_co_regulation_v1",
        )

        record_failure_and_check_escalation(store, wi.id, level1_record)
        record_failure_and_check_escalation(store, wi.id, level15_record)

        retrieved = store.get_work_item(wi.id)
        assert len(retrieved.failure_records) == 2

        # Level 1 record — no quality_scores
        l1 = next(fr for fr in retrieved.failure_records if "Level 1" in fr.failure_reason and fr.quality_scores is None)
        assert l1.quality_scores is None

        # Level 1.5 record — has quality_scores
        l15 = next(fr for fr in retrieved.failure_records if fr.quality_scores is not None)
        assert l15.reviewer_feedback == "Missing error handling."


# ---------------------------------------------------------------------------
# AC-5: No associated concept — escalation proceeds, label skipped
# ---------------------------------------------------------------------------


class TestEscalationWithMissingConcept:
    """AC-5: When get_concept returns None, escalation still proceeds without error.

    Tested with a mock store because the SQLiteStore FK constraint (work_items
    REFERENCES concepts) prevents orphaned work items in normal operation.
    The mock isolates the escalation logic and confirms the "label skip is silent"
    contract independently of storage-layer FK enforcement.
    """

    def _make_work_item_obj(self, concept_id: uuid.UUID, failure_count: int = 2) -> WorkItem:
        return WorkItem(
            concept_id=concept_id,
            item_type="verify_concept",
            description="test orphan",
            failure_count=failure_count,
        )

    def test_escalation_proceeds_when_concept_missing(self):
        """Given get_concept returns None, escalation sets escalated=True on the work item."""
        concept_id = uuid.uuid4()
        wi_after_record = self._make_work_item_obj(concept_id, failure_count=3)
        wi_after_escalate = wi_after_record.model_copy(update={"escalated": True})

        mock_store = MagicMock()
        mock_store.record_failure.return_value = wi_after_record
        mock_store.escalate_work_item.return_value = wi_after_escalate
        mock_store.get_concept.return_value = None  # concept not found

        record = _make_level1_failure_record()
        updated = record_failure_and_check_escalation(
            mock_store, wi_after_record.id, record, escalation_threshold=3
        )

        assert updated.escalated is True
        assert updated.failure_count == 3
        mock_store.escalate_work_item.assert_called_once()

    def test_update_concept_not_called_when_concept_missing(self):
        """When concept is missing, update_concept is never called (label skip is silent)."""
        concept_id = uuid.uuid4()
        wi_after_record = self._make_work_item_obj(concept_id, failure_count=3)
        wi_after_escalate = wi_after_record.model_copy(update={"escalated": True})

        mock_store = MagicMock()
        mock_store.record_failure.return_value = wi_after_record
        mock_store.escalate_work_item.return_value = wi_after_escalate
        mock_store.get_concept.return_value = None

        record = _make_level1_failure_record()
        record_failure_and_check_escalation(
            mock_store, wi_after_record.id, record, escalation_threshold=3
        )

        mock_store.update_concept.assert_not_called()

    def test_no_error_raised_when_concept_missing_during_escalation(self):
        """Escalation does not raise an exception when the concept is missing."""
        concept_id = uuid.uuid4()
        wi_after_record = self._make_work_item_obj(concept_id, failure_count=3)
        wi_after_escalate = wi_after_record.model_copy(update={"escalated": True})

        mock_store = MagicMock()
        mock_store.record_failure.return_value = wi_after_record
        mock_store.escalate_work_item.return_value = wi_after_escalate
        mock_store.get_concept.return_value = None

        record = _make_level1_failure_record()
        # Must not raise
        updated = record_failure_and_check_escalation(
            mock_store, wi_after_record.id, record, escalation_threshold=3
        )
        assert updated.escalated is True
