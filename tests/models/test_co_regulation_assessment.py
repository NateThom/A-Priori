"""Tests for CoRegulationAssessment model — traced to AC1, AC2, and DoD."""
import pytest
from pydantic import ValidationError

from apriori.models.co_regulation_assessment import CoRegulationAssessment


class TestCompositePass:
    """AC1: All scores at/above thresholds → composite_pass is True."""

    def test_all_scores_above_threshold_passes(self):
        # Given: specificity=0.7, structural_corroboration=0.7, completeness=0.7
        # with defaults 0.5 / 0.3 / 0.4
        # When: instantiated
        assessment = CoRegulationAssessment(
            specificity=0.7,
            structural_corroboration=0.7,
            completeness=0.7,
        )
        # Then: composite_pass is True
        assert assessment.composite_pass is True

    def test_scores_exactly_at_threshold_pass(self):
        # Boundary: scores equal to thresholds should also pass
        assessment = CoRegulationAssessment(
            specificity=0.5,
            structural_corroboration=0.3,
            completeness=0.4,
        )
        assert assessment.composite_pass is True


class TestCompositeFailure:
    """AC2: Any score below its threshold → composite_pass is False."""

    def test_specificity_below_threshold_fails(self):
        # Given: specificity=0.3 (below default threshold 0.5)
        # When: composite is computed
        assessment = CoRegulationAssessment(
            specificity=0.3,
            structural_corroboration=0.7,
            completeness=0.7,
        )
        # Then: composite_pass is False
        assert assessment.composite_pass is False

    def test_structural_corroboration_below_threshold_fails(self):
        assessment = CoRegulationAssessment(
            specificity=0.7,
            structural_corroboration=0.2,
            completeness=0.7,
        )
        assert assessment.composite_pass is False

    def test_completeness_below_threshold_fails(self):
        assessment = CoRegulationAssessment(
            specificity=0.7,
            structural_corroboration=0.7,
            completeness=0.3,
        )
        assert assessment.composite_pass is False


class TestCustomThresholds:
    """Thresholds are configurable; defaults are 0.5/0.3/0.4 (ERD §3.1.6)."""

    def test_custom_thresholds_respected(self):
        # A score that would fail at default threshold passes with a lower one
        assessment = CoRegulationAssessment(
            specificity=0.3,
            structural_corroboration=0.7,
            completeness=0.7,
            specificity_threshold=0.2,
        )
        assert assessment.composite_pass is True

    def test_default_thresholds(self):
        a = CoRegulationAssessment(
            specificity=0.5,
            structural_corroboration=0.3,
            completeness=0.4,
        )
        assert a.specificity_threshold == 0.5
        assert a.structural_corroboration_threshold == 0.3
        assert a.completeness_threshold == 0.4


class TestSerializationRoundTrip:
    """DoD: Serialization round-trips pass."""

    def test_round_trip(self):
        original = CoRegulationAssessment(
            specificity=0.7,
            structural_corroboration=0.7,
            completeness=0.7,
        )
        data = original.model_dump()
        reconstructed = CoRegulationAssessment(**data)
        assert reconstructed == original
        assert reconstructed.composite_pass is True
