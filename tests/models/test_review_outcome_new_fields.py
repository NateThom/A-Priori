"""Tests for new ReviewOutcome fields — traced to AC1, AC2, AC3 (flagged).

ERD §3.1.7 specifies: concept_id, reviewer, correction_details, created_at,
and the 'flagged' action value.
"""
import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from apriori.models.review_outcome import ReviewOutcome


SAMPLE_UUID = uuid.uuid4()


class TestRequiredFields:
    """AC1: concept_id and reviewer are required fields."""

    def test_concept_id_is_required(self):
        # Given: no concept_id provided
        # When: ReviewOutcome instantiated
        # Then: ValidationError is raised
        with pytest.raises(ValidationError):
            ReviewOutcome(action="verified", reviewer="alice")

    def test_reviewer_is_required(self):
        # Given: no reviewer provided
        # When: ReviewOutcome instantiated
        # Then: ValidationError is raised
        with pytest.raises(ValidationError):
            ReviewOutcome(action="verified", concept_id=SAMPLE_UUID)

    def test_concept_id_stored_as_uuid(self):
        # Given: valid concept_id (UUID) and reviewer
        # When: ReviewOutcome instantiated
        # Then: concept_id is a UUID instance
        outcome = ReviewOutcome(action="verified", concept_id=SAMPLE_UUID, reviewer="alice")
        assert outcome.concept_id == SAMPLE_UUID
        assert isinstance(outcome.concept_id, uuid.UUID)

    def test_reviewer_stored_as_str(self):
        # Given: reviewer provided
        # When: ReviewOutcome instantiated
        # Then: reviewer is stored correctly
        outcome = ReviewOutcome(action="verified", concept_id=SAMPLE_UUID, reviewer="alice")
        assert outcome.reviewer == "alice"


class TestCreatedAt:
    """AC1: created_at is auto-generated if not provided."""

    def test_created_at_auto_generated(self):
        # Given: no created_at provided
        # When: ReviewOutcome instantiated
        # Then: created_at is set automatically to a datetime
        outcome = ReviewOutcome(action="verified", concept_id=SAMPLE_UUID, reviewer="alice")
        assert isinstance(outcome.created_at, datetime)

    def test_created_at_can_be_provided(self):
        # Given: explicit created_at
        # When: ReviewOutcome instantiated
        # Then: the provided value is used
        ts = datetime(2025, 1, 1, 12, 0, 0)
        outcome = ReviewOutcome(
            action="verified", concept_id=SAMPLE_UUID, reviewer="alice", created_at=ts
        )
        assert outcome.created_at == ts


class TestFlaggedAction:
    """AC2: action='flagged' is a valid enum value (like 'verified', no error_type required)."""

    def test_flagged_action_passes_validation(self):
        # Given: action='flagged', concept_id and reviewer set
        # When: ReviewOutcome instantiated
        # Then: validation passes
        outcome = ReviewOutcome(action="flagged", concept_id=SAMPLE_UUID, reviewer="alice")
        assert outcome.action == "flagged"

    def test_flagged_action_error_type_is_none(self):
        # Given: action='flagged' (like 'verified', no error required)
        # When: ReviewOutcome instantiated
        # Then: error_type is None
        outcome = ReviewOutcome(action="flagged", concept_id=SAMPLE_UUID, reviewer="alice")
        assert outcome.error_type is None

    def test_flagged_action_with_error_type_raises(self):
        # Given: action='flagged' with error_type set
        # When: ReviewOutcome instantiated
        # Then: ValidationError raised (flagged does not require/allow error_type)
        with pytest.raises(ValidationError):
            ReviewOutcome(
                action="flagged",
                concept_id=SAMPLE_UUID,
                reviewer="alice",
                error_type="description_wrong",
            )


class TestCorrectionDetails:
    """AC1: correction_details is an optional field, required for 'corrected' action context."""

    def test_correction_details_defaults_to_none(self):
        # Given: no correction_details provided
        # When: ReviewOutcome instantiated with 'verified'
        # Then: correction_details is None
        outcome = ReviewOutcome(action="verified", concept_id=SAMPLE_UUID, reviewer="alice")
        assert outcome.correction_details is None

    def test_correction_details_can_be_set(self):
        # Given: correction_details provided with 'corrected' action
        # When: ReviewOutcome instantiated
        # Then: correction_details is stored
        outcome = ReviewOutcome(
            action="corrected",
            concept_id=SAMPLE_UUID,
            reviewer="alice",
            error_type="description_wrong",
            correction_details="Changed 'foo' to 'bar'",
        )
        assert outcome.correction_details == "Changed 'foo' to 'bar'"

    def test_correction_details_optional_for_corrected(self):
        # Given: action='corrected' without correction_details
        # When: ReviewOutcome instantiated
        # Then: validation passes (correction_details is truly optional)
        outcome = ReviewOutcome(
            action="corrected",
            concept_id=SAMPLE_UUID,
            reviewer="alice",
            error_type="description_wrong",
        )
        assert outcome.correction_details is None
