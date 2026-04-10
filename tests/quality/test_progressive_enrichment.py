"""Tests for progressive enrichment behavior — AC traceability: Story 13.1.

AC:
- Given a codebase with 500 files and coverage below 50%, when the librarian
  runs, then it prioritizes files near the developer's recent git activity
  over distant files.
- Given coverage exceeds 50%, when the priority engine recomputes, then
  standard weight distribution is restored.
- Given a token budget of $2.00, when the librarian runs, then it stays within
  budget and reports: "Analyzed 47/312 source files. Estimated remaining cost:
  ~$2.30 at current model pricing."
"""

from __future__ import annotations

import pytest

from apriori.config import DEFAULT_BASE_PRIORITIES
from apriori.models.run_telemetry import RunTelemetry
from apriori.quality.modulation import AdaptiveModulator


# ---------------------------------------------------------------------------
# AC1: Coverage < 50% → developer_proximity heavily weighted
# ---------------------------------------------------------------------------


class TestBootstrapModeActivation:
    """Bootstrap mode activates when coverage is below bootstrap_coverage_threshold."""

    def test_developer_proximity_boosted_when_coverage_below_threshold(self) -> None:
        """Given coverage=0.20 (below threshold=0.50), developer_proximity is boosted.

        AC: Given a codebase with 500 files and coverage below 50%, when the
        librarian runs, then it prioritizes files near developer's recent git
        activity over distant files.
        """
        modulator = AdaptiveModulator(
            base_weights=DEFAULT_BASE_PRIORITIES.copy(),
            bootstrap_coverage_threshold=0.50,
            bootstrap_developer_proximity_strength=2.0,
        )
        weights, telemetry = modulator.compute_effective_weights(
            coverage=0.20,
            freshness=0.90,
            blast_radius_completeness=0.80,
        )

        assert weights["developer_proximity"] > DEFAULT_BASE_PRIORITIES["developer_proximity"]
        assert telemetry.bootstrap_mode_active is True

    def test_developer_proximity_significantly_higher_in_bootstrap_mode(self) -> None:
        """Bootstrap mode produces a substantial boost — not just a rounding difference."""
        modulator = AdaptiveModulator(
            base_weights=DEFAULT_BASE_PRIORITIES.copy(),
            bootstrap_coverage_threshold=0.50,
            bootstrap_developer_proximity_strength=2.0,
        )
        weights, _ = modulator.compute_effective_weights(
            coverage=0.0,  # maximum deficit
            freshness=0.90,
            blast_radius_completeness=0.80,
        )

        # At coverage=0.0, proximity_deficit = (0.50 - 0.0) / 0.50 = 1.0
        # weight = base * (1 + 1.0 * 2.0) = base * 3
        expected = DEFAULT_BASE_PRIORITIES["developer_proximity"] * 3.0
        assert weights["developer_proximity"] == pytest.approx(expected, abs=1e-9)

    def test_bootstrap_boost_uses_proportional_deficit(self) -> None:
        """Boost is proportional to how far coverage is below the threshold."""
        modulator = AdaptiveModulator(
            base_weights=DEFAULT_BASE_PRIORITIES.copy(),
            bootstrap_coverage_threshold=0.50,
            bootstrap_developer_proximity_strength=2.0,
        )

        # coverage=0.25 → proximity_deficit = (0.50 - 0.25) / 0.50 = 0.50
        # weight = base * (1 + 0.50 * 2.0) = base * 2
        weights, _ = modulator.compute_effective_weights(
            coverage=0.25,
            freshness=0.90,
            blast_radius_completeness=0.80,
        )

        expected = DEFAULT_BASE_PRIORITIES["developer_proximity"] * 2.0
        assert weights["developer_proximity"] == pytest.approx(expected, abs=1e-9)

    def test_bootstrap_mode_active_in_telemetry_when_coverage_below_threshold(self) -> None:
        """Telemetry reports bootstrap_mode_active=True when coverage < threshold."""
        modulator = AdaptiveModulator(
            base_weights=DEFAULT_BASE_PRIORITIES.copy(),
            bootstrap_coverage_threshold=0.50,
        )
        _, telemetry = modulator.compute_effective_weights(
            coverage=0.30,
            freshness=0.90,
            blast_radius_completeness=0.80,
        )
        assert telemetry.bootstrap_mode_active is True

    def test_bootstrap_boost_configurable_strength(self) -> None:
        """bootstrap_developer_proximity_strength is configurable."""
        modulator = AdaptiveModulator(
            base_weights=DEFAULT_BASE_PRIORITIES.copy(),
            bootstrap_coverage_threshold=0.50,
            bootstrap_developer_proximity_strength=1.0,  # lower than default 2.0
        )
        weights, _ = modulator.compute_effective_weights(
            coverage=0.0,  # maximum deficit → proximity_deficit = 1.0
            freshness=0.90,
            blast_radius_completeness=0.80,
        )
        # weight = base * (1 + 1.0 * 1.0) = base * 2
        expected = DEFAULT_BASE_PRIORITIES["developer_proximity"] * 2.0
        assert weights["developer_proximity"] == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# AC2: Coverage >= 50% → standard weight distribution restored
# ---------------------------------------------------------------------------


class TestBootstrapModeDeactivation:
    """Bootstrap mode deactivates when coverage meets or exceeds the threshold."""

    def test_developer_proximity_at_base_weight_when_coverage_at_threshold(self) -> None:
        """Given coverage exactly at threshold (0.50), developer_proximity is at base weight.

        AC: Given coverage exceeds 50%, when the priority engine recomputes,
        then standard weight distribution is restored.
        """
        modulator = AdaptiveModulator(
            base_weights=DEFAULT_BASE_PRIORITIES.copy(),
            bootstrap_coverage_threshold=0.50,
            bootstrap_developer_proximity_strength=2.0,
        )
        weights, telemetry = modulator.compute_effective_weights(
            coverage=0.50,
            freshness=0.90,
            blast_radius_completeness=0.80,
        )

        assert weights["developer_proximity"] == pytest.approx(
            DEFAULT_BASE_PRIORITIES["developer_proximity"], abs=1e-9
        )
        assert telemetry.bootstrap_mode_active is False

    def test_developer_proximity_at_base_weight_when_coverage_above_threshold(self) -> None:
        """Given coverage=0.70 (above threshold=0.50), standard weights apply."""
        modulator = AdaptiveModulator(
            base_weights=DEFAULT_BASE_PRIORITIES.copy(),
            bootstrap_coverage_threshold=0.50,
            bootstrap_developer_proximity_strength=2.0,
        )
        weights, telemetry = modulator.compute_effective_weights(
            coverage=0.70,
            freshness=0.90,
            blast_radius_completeness=0.80,
        )

        assert weights["developer_proximity"] == pytest.approx(
            DEFAULT_BASE_PRIORITIES["developer_proximity"], abs=1e-9
        )
        assert telemetry.bootstrap_mode_active is False

    def test_all_other_weights_unchanged_when_coverage_above_threshold(self) -> None:
        """When coverage is above threshold, no other weights are affected by bootstrap."""
        modulator = AdaptiveModulator(
            base_weights=DEFAULT_BASE_PRIORITIES.copy(),
            bootstrap_coverage_threshold=0.50,
            modulation_strength=0.0,  # disable regular modulation to isolate bootstrap
        )
        weights, _ = modulator.compute_effective_weights(
            coverage=0.60,
            freshness=0.90,
            blast_radius_completeness=0.80,
        )

        for factor in DEFAULT_BASE_PRIORITIES:
            assert weights[factor] == pytest.approx(
                DEFAULT_BASE_PRIORITIES[factor], abs=1e-9
            ), f"Factor {factor!r} should not change above coverage threshold"

    def test_bootstrap_mode_inactive_in_telemetry_when_coverage_above_threshold(self) -> None:
        """Telemetry reports bootstrap_mode_active=False when coverage >= threshold."""
        modulator = AdaptiveModulator(
            base_weights=DEFAULT_BASE_PRIORITIES.copy(),
            bootstrap_coverage_threshold=0.50,
        )
        _, telemetry = modulator.compute_effective_weights(
            coverage=0.80,
            freshness=0.90,
            blast_radius_completeness=0.80,
        )
        assert telemetry.bootstrap_mode_active is False


# ---------------------------------------------------------------------------
# Bootstrap mode disabled when threshold is None
# ---------------------------------------------------------------------------


class TestBootstrapModeDisabled:
    """When bootstrap_coverage_threshold is None (default), bootstrap is off."""

    def test_developer_proximity_unchanged_when_bootstrap_disabled(self) -> None:
        """When bootstrap_coverage_threshold is None, developer_proximity is at base weight
        regardless of coverage level."""
        modulator = AdaptiveModulator(
            base_weights=DEFAULT_BASE_PRIORITIES.copy(),
            # bootstrap_coverage_threshold not set → defaults to None
            modulation_strength=0.0,  # disable regular modulation too
        )
        weights, telemetry = modulator.compute_effective_weights(
            coverage=0.05,  # very low coverage — would trigger bootstrap if enabled
            freshness=0.90,
            blast_radius_completeness=0.80,
        )

        assert weights["developer_proximity"] == pytest.approx(
            DEFAULT_BASE_PRIORITIES["developer_proximity"], abs=1e-9
        )
        assert telemetry.bootstrap_mode_active is False

    def test_telemetry_bootstrap_mode_false_when_threshold_none(self) -> None:
        """bootstrap_mode_active is always False when threshold is not configured."""
        modulator = AdaptiveModulator(
            base_weights=DEFAULT_BASE_PRIORITIES.copy(),
        )
        _, telemetry = modulator.compute_effective_weights(
            coverage=0.0,
            freshness=0.9,
            blast_radius_completeness=0.8,
        )
        assert telemetry.bootstrap_mode_active is False


# ---------------------------------------------------------------------------
# Bootstrap mode combines with regular modulation
# ---------------------------------------------------------------------------


class TestBootstrapCombinesWithModulation:
    """Bootstrap developer_proximity boost stacks with regular coverage_gap modulation."""

    def test_bootstrap_and_coverage_modulation_both_apply(self) -> None:
        """Both bootstrap (developer_proximity) and coverage deficit (coverage_gap)
        modulation apply simultaneously when coverage is below the threshold."""
        modulator = AdaptiveModulator(
            base_weights=DEFAULT_BASE_PRIORITIES.copy(),
            coverage_target=0.80,
            modulation_strength=1.0,
            bootstrap_coverage_threshold=0.50,
            bootstrap_developer_proximity_strength=2.0,
        )
        weights, telemetry = modulator.compute_effective_weights(
            coverage=0.20,
            freshness=0.90,
            blast_radius_completeness=0.80,
        )

        # coverage_gap modulation: 0.15 * (1 + 0.60 * 1.0) = 0.15 * 1.60 = 0.24
        assert weights["coverage_gap"] == pytest.approx(0.15 * (1 + 0.60 * 1.0), abs=1e-9)

        # developer_proximity bootstrap: proximity_deficit = (0.50 - 0.20)/0.50 = 0.60
        # weight = 0.25 * (1 + 0.60 * 2.0) = 0.25 * 2.20 = 0.55
        expected_prox = 0.25 * (1 + 0.60 * 2.0)
        assert weights["developer_proximity"] == pytest.approx(expected_prox, abs=1e-9)

        assert telemetry.bootstrap_mode_active is True

    def test_needs_review_and_git_activity_unchanged_during_bootstrap(self) -> None:
        """needs_review and git_activity weights are not affected by bootstrap mode."""
        modulator = AdaptiveModulator(
            base_weights=DEFAULT_BASE_PRIORITIES.copy(),
            bootstrap_coverage_threshold=0.50,
            bootstrap_developer_proximity_strength=2.0,
            modulation_strength=0.0,
        )
        weights, _ = modulator.compute_effective_weights(
            coverage=0.10,  # triggers bootstrap
            freshness=0.90,
            blast_radius_completeness=0.80,
        )

        assert weights["needs_review"] == pytest.approx(
            DEFAULT_BASE_PRIORITIES["needs_review"], abs=1e-9
        )
        assert weights["git_activity"] == pytest.approx(
            DEFAULT_BASE_PRIORITIES["git_activity"], abs=1e-9
        )
        assert weights["failure_urgency"] == pytest.approx(
            DEFAULT_BASE_PRIORITIES["failure_urgency"], abs=1e-9
        )


# ---------------------------------------------------------------------------
# AC3: Cost estimation reporting in RunTelemetry
# ---------------------------------------------------------------------------


class TestCostEstimationReport:
    """format_progress_report produces correct cost estimation output.

    AC: Given a token budget of $2.00, when the librarian runs, then it stays
    within budget and reports: "Analyzed 47/312 source files. Estimated
    remaining cost: ~$2.30 at current model pricing."
    """

    def test_progress_report_includes_file_counts(self) -> None:
        """Report includes files analyzed and total source files."""
        telemetry = RunTelemetry(files_analyzed=47, total_tokens=10000)
        report = telemetry.format_progress_report(
            total_source_files=312,
            cost_per_1k_tokens=0.015,
        )
        assert "47" in report
        assert "312" in report

    def test_progress_report_includes_estimated_cost(self) -> None:
        """Report includes estimated remaining cost with 'at current model pricing'."""
        telemetry = RunTelemetry(files_analyzed=47, total_tokens=10000)
        report = telemetry.format_progress_report(
            total_source_files=312,
            cost_per_1k_tokens=0.015,
        )
        assert "Estimated remaining cost" in report
        assert "at current model pricing" in report

    def test_progress_report_format_matches_ac(self) -> None:
        """Report format: 'Analyzed X/Y source files. Estimated remaining cost: ~$Z at ...'"""
        telemetry = RunTelemetry(files_analyzed=47, total_tokens=10000)
        report = telemetry.format_progress_report(
            total_source_files=312,
            cost_per_1k_tokens=0.015,
        )
        assert report.startswith("Analyzed 47/312 source files.")
        assert "~$" in report

    def test_estimated_cost_calculation_is_correct(self) -> None:
        """Estimated remaining cost = cost_per_file * remaining_files.

        cost_per_file = (total_tokens / 1000) * cost_per_1k_tokens / files_analyzed
        remaining = total_source_files - files_analyzed
        estimated = cost_per_file * remaining
        """
        # 100 files analyzed, 10000 tokens used → cost = 10000/1000 * 0.01 = $0.10
        # cost_per_file = 0.10 / 100 = $0.001
        # remaining = 200 - 100 = 100 files
        # estimated_remaining = 0.001 * 100 = $0.10
        telemetry = RunTelemetry(files_analyzed=100, total_tokens=10000)
        report = telemetry.format_progress_report(
            total_source_files=200,
            cost_per_1k_tokens=0.01,
        )
        assert "$0.10" in report

    def test_progress_report_zero_files_analyzed_graceful(self) -> None:
        """When no files have been analyzed, report handles zero gracefully."""
        telemetry = RunTelemetry(files_analyzed=0, total_tokens=0)
        report = telemetry.format_progress_report(
            total_source_files=312,
            cost_per_1k_tokens=0.015,
        )
        # Should not crash; should still include file counts
        assert "0/312" in report

    def test_files_analyzed_field_defaults_to_zero(self) -> None:
        """RunTelemetry.files_analyzed defaults to 0."""
        telemetry = RunTelemetry()
        assert telemetry.files_analyzed == 0

    def test_progress_report_all_analyzed_shows_zero_remaining_cost(self) -> None:
        """When all files are analyzed, estimated remaining cost is $0.00."""
        telemetry = RunTelemetry(files_analyzed=312, total_tokens=50000)
        report = telemetry.format_progress_report(
            total_source_files=312,
            cost_per_1k_tokens=0.015,
        )
        assert "$0.00" in report


# ---------------------------------------------------------------------------
# Config integration: LibrarianConfig bootstrap fields
# ---------------------------------------------------------------------------


class TestConfigBootstrapFields:
    """bootstrap fields are present on LibrarianConfig with correct defaults."""

    def test_librarian_config_has_bootstrap_coverage_threshold(self) -> None:
        """LibrarianConfig has bootstrap_coverage_threshold defaulting to 0.50."""
        from apriori.config import LibrarianConfig

        config = LibrarianConfig()
        assert config.bootstrap_coverage_threshold == pytest.approx(0.50)

    def test_librarian_config_has_bootstrap_developer_proximity_strength(self) -> None:
        """LibrarianConfig has bootstrap_developer_proximity_strength defaulting to 2.0."""
        from apriori.config import LibrarianConfig

        config = LibrarianConfig()
        assert config.bootstrap_developer_proximity_strength == pytest.approx(2.0)

    def test_budget_config_has_cost_per_1k_tokens(self) -> None:
        """BudgetConfig has cost_per_1k_tokens with a sensible default."""
        from apriori.config import BudgetConfig

        config = BudgetConfig()
        assert config.cost_per_1k_tokens > 0.0
