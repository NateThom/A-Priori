"""Tests for ReviewOutcome model — traced to AC3, AC4, AC5, and DoD."""
import uuid

import pytest
from pydantic import ValidationError

from apriori.models.review_outcome import ReviewOutcome

CONCEPT_ID = uuid.uuid4()
REVIEWER = "alice"


class TestCorrectedAction:
    """AC3: action='corrected' + valid error_type → validation passes."""

    def test_corrected_with_error_type_passes(self):
        # Given: action="corrected", error_type="relationship_missing"
        # When: instantiated
        outcome = ReviewOutcome(
            action="corrected",
            concept_id=CONCEPT_ID,
            reviewer=REVIEWER,
            error_type="relationship_missing",
        )
        # Then: validation passes
        assert outcome.action == "corrected"
        assert outcome.error_type == "relationship_missing"

    def test_all_valid_error_types_accepted(self):
        valid_types = [
            "description_wrong",
            "relationship_missing",
            "relationship_hallucinated",
            "confidence_miscalibrated",
            "other",
        ]
        for error_type in valid_types:
            outcome = ReviewOutcome(
                action="corrected",
                concept_id=CONCEPT_ID,
                reviewer=REVIEWER,
                error_type=error_type,
            )
            assert outcome.error_type == error_type

    def test_corrected_without_error_type_raises(self):
        # AC5: action='corrected' with no error_type → validation error
        # Given: action="corrected", no error_type
        # When: instantiated
        # Then: validation raises an error
        with pytest.raises(ValidationError):
            ReviewOutcome(action="corrected", concept_id=CONCEPT_ID, reviewer=REVIEWER)

    def test_corrected_with_invalid_error_type_raises(self):
        with pytest.raises(ValidationError):
            ReviewOutcome(
                action="corrected",
                concept_id=CONCEPT_ID,
                reviewer=REVIEWER,
                error_type="made_up_type",
            )


class TestVerifiedAction:
    """AC4: action='verified' + error_type set → validation raises error."""

    def test_verified_without_error_type_passes(self):
        outcome = ReviewOutcome(action="verified", concept_id=CONCEPT_ID, reviewer=REVIEWER)
        assert outcome.action == "verified"
        assert outcome.error_type is None

    def test_verified_with_error_type_raises(self):
        # AC4: Given action="verified" and an error_type set
        # When: instantiated
        # Then: validation raises an error
        with pytest.raises(ValidationError):
            ReviewOutcome(
                action="verified",
                concept_id=CONCEPT_ID,
                reviewer=REVIEWER,
                error_type="relationship_missing",
            )


class TestSerializationRoundTrip:
    """DoD: Serialization round-trips pass."""

    def test_round_trip_corrected(self):
        original = ReviewOutcome(
            action="corrected",
            concept_id=CONCEPT_ID,
            reviewer=REVIEWER,
            error_type="other",
        )
        data = original.model_dump()
        reconstructed = ReviewOutcome(**data)
        assert reconstructed == original

    def test_round_trip_verified(self):
        original = ReviewOutcome(action="verified", concept_id=CONCEPT_ID, reviewer=REVIEWER)
        data = original.model_dump()
        reconstructed = ReviewOutcome(**data)
        assert reconstructed == original
