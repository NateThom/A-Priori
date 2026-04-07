"""Tests for ReviewService — AC traceability: Story 7.6.

AC-1 (verify): Given a concept, when a human marks it as "verified", then
    verified_by and last_verified are set on the concept, confidence is boosted
    by +0.1 (capped at 1.0), and a ReviewOutcome is recorded.

AC-2 (correct): Given a concept, when a human submits a "corrected" action
    with error_type="relationship_missing", then the concept is updated, the
    correction is recorded, and the ReviewOutcome is stored.

AC-3 (flag): Given a concept, when a human "flags" it, then "needs-review"
    label is applied, a ReviewOutcome is recorded, and a "review_concept"
    WorkItem is created.

AC-4 (error profile): Given 20 review outcomes over the past 30 days, when
    get_error_profile is called, then it returns an aggregated summary showing
    the distribution of error types.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apriori.models.concept import Concept
from apriori.models.review_outcome import ReviewOutcome
from apriori.models.work_item import WorkItem
from apriori.storage.sqlite_store import SQLiteStore
from apriori.knowledge.reviewer import ReviewService, ErrorProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_concept(**kwargs) -> Concept:
    defaults = dict(name="TestConcept", description="A test concept.", created_by="agent")
    defaults.update(kwargs)
    return Concept(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "test.db")


@pytest.fixture()
def service(store: SQLiteStore) -> ReviewService:
    return ReviewService(store)


@pytest.fixture()
def concept(store: SQLiteStore) -> Concept:
    c = _make_concept(confidence=0.5)
    return store.create_concept(c)


# ---------------------------------------------------------------------------
# AC-1: verify_concept
# ---------------------------------------------------------------------------

class TestVerifyConcept:
    """AC-1: verify action sets verified_by, last_verified, boosts confidence, records outcome."""

    def test_verify_sets_verified_by(self, service: ReviewService, concept: Concept):
        # Given: a concept with verified_by=None
        assert concept.verified_by is None
        # When: verify_concept called
        updated, outcome = service.verify_concept(concept.id, reviewer="alice")
        # Then: verified_by is set
        assert updated.verified_by == "alice"

    def test_verify_sets_last_verified(self, service: ReviewService, concept: Concept):
        # Given: a concept with last_verified=None
        assert concept.last_verified is None
        # When: verify_concept called
        updated, outcome = service.verify_concept(concept.id, reviewer="alice")
        # Then: last_verified is set to a datetime
        assert updated.last_verified is not None
        assert isinstance(updated.last_verified, datetime)

    def test_verify_boosts_confidence_by_01(self, service: ReviewService, concept: Concept):
        # Given: concept with confidence=0.5
        assert concept.confidence == 0.5
        # When: verify_concept called
        updated, outcome = service.verify_concept(concept.id, reviewer="alice")
        # Then: confidence boosted by 0.1
        assert updated.confidence == pytest.approx(0.6)

    def test_verify_caps_confidence_at_10(self, service: ReviewService, store: SQLiteStore):
        # Given: concept with confidence=0.95
        c = _make_concept(confidence=0.95)
        stored = store.create_concept(c)
        # When: verify_concept called
        updated, outcome = service.verify_concept(stored.id, reviewer="alice")
        # Then: confidence is capped at 1.0
        assert updated.confidence == pytest.approx(1.0)

    def test_verify_already_at_max_stays_at_10(self, service: ReviewService, store: SQLiteStore):
        # Given: concept with confidence=1.0
        c = _make_concept(confidence=1.0)
        stored = store.create_concept(c)
        # When: verify_concept called
        updated, outcome = service.verify_concept(stored.id, reviewer="bob")
        # Then: confidence stays at 1.0
        assert updated.confidence == pytest.approx(1.0)

    def test_verify_records_review_outcome(self, service: ReviewService, concept: Concept, store: SQLiteStore):
        # When: verify_concept called
        updated, outcome = service.verify_concept(concept.id, reviewer="alice")
        # Then: a ReviewOutcome is recorded in storage
        assert isinstance(outcome, ReviewOutcome)
        assert outcome.action == "verified"
        assert outcome.concept_id == concept.id
        assert outcome.reviewer == "alice"
        assert outcome.error_type is None

    def test_verify_outcome_persisted_to_store(self, service: ReviewService, concept: Concept, store: SQLiteStore):
        # When: verify_concept called
        service.verify_concept(concept.id, reviewer="alice")
        # Then: outcome is retrievable from storage
        outcomes = store.get_review_outcomes_for_concept(concept.id)
        assert len(outcomes) == 1
        assert outcomes[0].action == "verified"

    def test_verify_concept_persisted_to_store(self, service: ReviewService, concept: Concept, store: SQLiteStore):
        # When: verify_concept called
        service.verify_concept(concept.id, reviewer="alice")
        # Then: concept in store has updated verified_by
        persisted = store.get_concept(concept.id)
        assert persisted is not None
        assert persisted.verified_by == "alice"
        assert persisted.confidence == pytest.approx(0.6)

    def test_verify_raises_on_missing_concept(self, service: ReviewService):
        # Given: non-existent concept_id
        # When: verify_concept called
        # Then: KeyError raised
        with pytest.raises(KeyError):
            service.verify_concept(uuid.uuid4(), reviewer="alice")


# ---------------------------------------------------------------------------
# AC-2: correct_concept
# ---------------------------------------------------------------------------

class TestCorrectConcept:
    """AC-2: correct action updates concept, records ReviewOutcome with error_type."""

    def test_correct_records_outcome_with_error_type(
        self, service: ReviewService, concept: Concept
    ):
        # Given: a concept and error_type="relationship_missing"
        # When: correct_concept called
        updated, outcome = service.correct_concept(
            concept.id,
            reviewer="bob",
            error_type="relationship_missing",
            correction_details="Edge to DatabasePool is missing.",
        )
        # Then: ReviewOutcome recorded with correct fields
        assert outcome.action == "corrected"
        assert outcome.error_type == "relationship_missing"
        assert outcome.correction_details == "Edge to DatabasePool is missing."
        assert outcome.reviewer == "bob"
        assert outcome.concept_id == concept.id

    def test_correct_outcome_persisted_to_store(
        self, service: ReviewService, concept: Concept, store: SQLiteStore
    ):
        # When: correct_concept called
        service.correct_concept(
            concept.id,
            reviewer="bob",
            error_type="relationship_missing",
        )
        # Then: outcome is retrievable from storage
        outcomes = store.get_review_outcomes_for_concept(concept.id)
        assert len(outcomes) == 1
        assert outcomes[0].action == "corrected"
        assert outcomes[0].error_type == "relationship_missing"

    def test_correct_concept_updated_at_changes(
        self, service: ReviewService, concept: Concept, store: SQLiteStore
    ):
        # When: correct_concept called
        original_updated_at = concept.updated_at
        updated, outcome = service.correct_concept(
            concept.id,
            reviewer="bob",
            error_type="description_wrong",
        )
        # Then: concept's updated_at is refreshed
        assert updated.updated_at >= original_updated_at

    def test_correct_all_valid_error_types(
        self, service: ReviewService, store: SQLiteStore
    ):
        # Given: all valid error types
        valid_types = [
            "description_wrong",
            "relationship_missing",
            "relationship_hallucinated",
            "confidence_miscalibrated",
            "other",
        ]
        for error_type in valid_types:
            c = _make_concept(name=f"Concept_{error_type}")
            stored = store.create_concept(c)
            updated, outcome = service.correct_concept(
                stored.id, reviewer="bob", error_type=error_type
            )
            assert outcome.error_type == error_type

    def test_correct_raises_on_missing_concept(self, service: ReviewService):
        # Given: non-existent concept_id
        # When/Then: KeyError raised
        with pytest.raises(KeyError):
            service.correct_concept(
                uuid.uuid4(),
                reviewer="bob",
                error_type="description_wrong",
            )


# ---------------------------------------------------------------------------
# AC-3: flag_concept
# ---------------------------------------------------------------------------

class TestFlagConcept:
    """AC-3: flag applies needs-review label, records ReviewOutcome, creates WorkItem."""

    def test_flag_applies_needs_review_label(
        self, service: ReviewService, concept: Concept, store: SQLiteStore
    ):
        # Given: a concept without needs-review label
        assert "needs-review" not in concept.labels
        # When: flag_concept called
        updated, outcome, work_item = service.flag_concept(concept.id, reviewer="carol")
        # Then: needs-review label applied
        assert "needs-review" in updated.labels

    def test_flag_records_review_outcome(
        self, service: ReviewService, concept: Concept
    ):
        # When: flag_concept called
        updated, outcome, work_item = service.flag_concept(concept.id, reviewer="carol")
        # Then: ReviewOutcome recorded with action="flagged"
        assert outcome.action == "flagged"
        assert outcome.reviewer == "carol"
        assert outcome.concept_id == concept.id
        assert outcome.error_type is None

    def test_flag_outcome_persisted_to_store(
        self, service: ReviewService, concept: Concept, store: SQLiteStore
    ):
        # When: flag_concept called
        service.flag_concept(concept.id, reviewer="carol")
        # Then: outcome is retrievable from storage
        outcomes = store.get_review_outcomes_for_concept(concept.id)
        assert len(outcomes) == 1
        assert outcomes[0].action == "flagged"

    def test_flag_creates_review_concept_work_item(
        self, service: ReviewService, concept: Concept
    ):
        # When: flag_concept called
        updated, outcome, work_item = service.flag_concept(concept.id, reviewer="carol")
        # Then: a review_concept WorkItem is created
        assert isinstance(work_item, WorkItem)
        assert work_item.item_type == "review_concept"
        assert work_item.concept_id == concept.id

    def test_flag_work_item_persisted_to_store(
        self, service: ReviewService, concept: Concept, store: SQLiteStore
    ):
        # When: flag_concept called
        updated, outcome, work_item = service.flag_concept(concept.id, reviewer="carol")
        # Then: work item is retrievable from storage
        retrieved = store.get_work_item(work_item.id)
        assert retrieved is not None
        assert retrieved.item_type == "review_concept"
        assert retrieved.concept_id == concept.id

    def test_flag_concept_persisted_with_label(
        self, service: ReviewService, concept: Concept, store: SQLiteStore
    ):
        # When: flag_concept called
        service.flag_concept(concept.id, reviewer="carol")
        # Then: concept in store has needs-review label
        persisted = store.get_concept(concept.id)
        assert persisted is not None
        assert "needs-review" in persisted.labels

    def test_flag_idempotent_label(
        self, service: ReviewService, store: SQLiteStore
    ):
        # Given: concept already has needs-review label
        c = _make_concept(labels={"needs-review"})
        stored = store.create_concept(c)
        # When: flag_concept called again
        updated, outcome, work_item = service.flag_concept(stored.id, reviewer="carol")
        # Then: label not duplicated (set semantics)
        assert updated.labels.count("needs-review") == 1 if isinstance(updated.labels, list) else True
        assert "needs-review" in updated.labels

    def test_flag_raises_on_missing_concept(self, service: ReviewService):
        # Given: non-existent concept_id
        # When/Then: KeyError raised
        with pytest.raises(KeyError):
            service.flag_concept(uuid.uuid4(), reviewer="carol")


# ---------------------------------------------------------------------------
# AC-4: get_error_profile
# ---------------------------------------------------------------------------

class TestGetErrorProfile:
    """AC-4: get_error_profile aggregates error_type distribution over past N days."""

    def _create_outcome(
        self,
        store: SQLiteStore,
        concept_id: uuid.UUID,
        action: str,
        error_type: str | None,
        days_ago: int,
    ) -> ReviewOutcome:
        """Helper to create a ReviewOutcome with a specific created_at timestamp."""
        created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
        outcome = ReviewOutcome(
            concept_id=concept_id,
            reviewer="tester",
            action=action,  # type: ignore[arg-type]
            error_type=error_type,
            created_at=created_at,
        )
        return store.create_review_outcome(outcome)

    def test_error_profile_returns_error_type_distribution(
        self, service: ReviewService, store: SQLiteStore
    ):
        # Given: 20 review outcomes over the past 30 days with various error_types
        c = _make_concept()
        concept = store.create_concept(c)
        cid = concept.id

        # 8 "relationship_missing", 7 "description_wrong", 5 "other" (= 20 total)
        for _ in range(8):
            self._create_outcome(store, cid, "corrected", "relationship_missing", days_ago=5)
        for _ in range(7):
            self._create_outcome(store, cid, "corrected", "description_wrong", days_ago=10)
        for _ in range(5):
            self._create_outcome(store, cid, "corrected", "other", days_ago=20)

        # When: get_error_profile called with days=30
        profile = service.get_error_profile(days=30)

        # Then: distribution reflects the 20 corrected outcomes
        assert isinstance(profile, ErrorProfile)
        assert profile.total_outcomes >= 20
        assert profile.error_type_counts.get("relationship_missing", 0) == 8
        assert profile.error_type_counts.get("description_wrong", 0) == 7
        assert profile.error_type_counts.get("other", 0) == 5

    def test_error_profile_excludes_outcomes_older_than_days(
        self, service: ReviewService, store: SQLiteStore
    ):
        # Given: outcomes both inside and outside the window
        c = _make_concept()
        concept = store.create_concept(c)
        cid = concept.id

        # 3 outcomes within 30 days
        for _ in range(3):
            self._create_outcome(store, cid, "corrected", "description_wrong", days_ago=5)
        # 10 outcomes older than 30 days
        for _ in range(10):
            self._create_outcome(store, cid, "corrected", "relationship_missing", days_ago=40)

        # When: get_error_profile called with days=30
        profile = service.get_error_profile(days=30)

        # Then: only outcomes within the window are counted
        assert profile.error_type_counts.get("description_wrong", 0) == 3
        assert profile.error_type_counts.get("relationship_missing", 0) == 0

    def test_error_profile_excludes_verified_and_flagged_from_error_types(
        self, service: ReviewService, store: SQLiteStore
    ):
        # Given: a mix of verified, flagged, and corrected outcomes
        c = _make_concept()
        concept = store.create_concept(c)
        cid = concept.id

        self._create_outcome(store, cid, "verified", None, days_ago=1)
        self._create_outcome(store, cid, "flagged", None, days_ago=1)
        self._create_outcome(store, cid, "corrected", "other", days_ago=1)

        # When: get_error_profile called
        profile = service.get_error_profile(days=30)

        # Then: error_type_counts only includes corrected outcomes with error_type
        assert profile.total_outcomes == 3  # all 3 counted in total
        assert profile.error_type_counts.get("other", 0) == 1
        assert None not in profile.error_type_counts

    def test_error_profile_empty_when_no_outcomes(
        self, service: ReviewService, store: SQLiteStore
    ):
        # Given: no outcomes in store
        # When: get_error_profile called
        profile = service.get_error_profile(days=30)
        # Then: empty profile returned
        assert profile.total_outcomes == 0
        assert profile.error_type_counts == {}

    def test_error_profile_action_counts(
        self, service: ReviewService, store: SQLiteStore
    ):
        # Given: mix of actions
        c = _make_concept()
        concept = store.create_concept(c)
        cid = concept.id

        for _ in range(5):
            self._create_outcome(store, cid, "verified", None, days_ago=1)
        for _ in range(3):
            self._create_outcome(store, cid, "flagged", None, days_ago=1)
        for _ in range(4):
            self._create_outcome(store, cid, "corrected", "description_wrong", days_ago=1)

        # When: get_error_profile called
        profile = service.get_error_profile(days=30)

        # Then: action_counts reflects distribution
        assert profile.action_counts.get("verified", 0) == 5
        assert profile.action_counts.get("flagged", 0) == 3
        assert profile.action_counts.get("corrected", 0) == 4
        assert profile.total_outcomes == 12

    def test_error_profile_default_days_is_30(
        self, service: ReviewService, store: SQLiteStore
    ):
        # Given: an outcome 25 days ago (within default 30-day window)
        c = _make_concept()
        concept = store.create_concept(c)
        self._create_outcome(store, concept.id, "corrected", "other", days_ago=25)

        # When: get_error_profile called without days arg
        profile = service.get_error_profile()

        # Then: the outcome is included
        assert profile.total_outcomes == 1
